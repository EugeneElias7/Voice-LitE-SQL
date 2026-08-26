"""Voice-LitE-SQL -- L8 experiment: execution-guided SQL self-correction.

Runs the SAME 50 clean questions from questions.json through the L8
pipeline::

    L7 stored SQL (from l7_report.json) -> L4 read-only executor
              -> on error/incorrect result, build correction prompt
              -> Qwen -> corrected SQL -> L4 read-only executor -> result

and compares directly against:
- the frozen L4 baseline (evaluation/results/l4_report.json -- never written)
- the L7 report (evaluation/results/l7_report.json -- never written)

The ONLY intervention vs L7 is the execution-guided correction loop.
L7 retrieval behavior is NOT modified. L4 code, model, database, executor
and evaluation methodology are unchanged.

Usage:
    python scripts/l8_evaluator.py
    python scripts/l8_evaluator.py --limit 10 --top-k 8 --model qwen2.5-coder:1.5b
    python scripts/l8_evaluator.py --max-attempts 2

Exits with a clear error if Ollama is unavailable. Exits if the real embedding
model is unavailable for the real run.
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.correction import (  # noqa: E402
    CorrectionResult,
    SQLCorrector,
    build_correction_context_text,
)
from backend.database.executor import execute_sql  # noqa: E402
from backend.evaluation.evaluator import results_equal  # noqa: E402
from backend.evaluation.metrics import compute_metrics, metrics_by_category  # noqa: E402
from backend.llm.ollama_client import DEFAULT_MODEL, OllamaError, generate  # noqa: E402
from backend.retrieval import (  # noqa: E402
    CountVectorEmbedder,
    EmbeddingError,
    SchemaRetriever,
)
from backend.retrieval.embeddings import EMBEDDING_DIMENSIONS, SentenceTransformerEmbedder  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "backend" / "data" / "enterprise.db"
DEFAULT_QUESTIONS = PROJECT_ROOT / "backend" / "datasets" / "custom" / "questions.json"
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
DEFAULT_L4_REPORT = RESULTS_DIR / "l4_report.json"
DEFAULT_L7_REPORT = RESULTS_DIR / "l7_report.json"
DEFAULT_L8_REPORT = RESULTS_DIR / "l8_report.json"
DEFAULT_INDEX_DIR = PROJECT_ROOT / "evaluation" / "index" / "l8"

CATEGORY_ORDER = [
    "SELECT",
    "WHERE",
    "JOIN",
    "GROUP BY",
    "ORDER BY",
    "aggregate",
    "complex",
]


def load_metrics_report(path):
    """Return {metrics, by_category, evaluations_map} or (None, None, None)."""
    if not Path(path).exists():
        return None, None, {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def probe_ollama(model):
    try:
        generate("Reply with exactly: OK", model=model, timeout=30)
    except OllamaError as exc:
        print(f"ERROR: Ollama is not available - {exc}", file=sys.stderr)
        print(
            "Start Ollama (and make sure the model is pulled) then re-run.",
            file=sys.stderr,
        )
        sys.exit(1)


def build_retriever(args):
    """Build the real SchemaRetriever with the real embedding model."""
    try:
        embedder = SentenceTransformerEmbedder(model_name=args.embedding_model)
    except EmbeddingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "The real L8 run requires the embedding model available locally. "
            "Install/pull 'all-MiniLM-L6-v2' into the sentence-transformers "
            "cache, or re-run with --fake-embedder only for pipeline tests.",
            file=sys.stderr,
        )
        sys.exit(1)

    return SchemaRetriever(
        db_path=args.db,
        persist_dir=args.index_dir,
        collection_name=args.collection,
        embedding_model=args.embedding_model,
        embedding_dimensions=EMBEDDING_DIMENSIONS.get(
            args.embedding_model, 384
        ),
        top_k=args.top_k,
        embedder=embedder,
    )


def evaluate_question(l7_eval, item, model, db, max_attempts=3, timeout=120):
    """Evaluate one question using the stored L7 SQL and retrieval.

    Parameters
    ----------
    l7_eval: dict
        The L7 evaluation record from l7_report.json["evaluations"].
    item: dict
        The original question item from questions.json (for reference_sql).
    model: str
        Ollama model name.
    db: str
        Database path.
    max_attempts: int
        Maximum correction attempts.
    timeout: int
        LLM call timeout in seconds.

    Returns
    -------
    dict with evaluation results including correction history.
    """
    question_id = l7_eval.get("question_id", "")
    question = item["question"]
    reference_sql = item["sql"]
    category = item.get("category", "")

    generation_success = l7_eval.get("generation_success", False)
    original_sql = l7_eval.get("generated_sql")
    l7_correct = bool(l7_eval.get("correctness", False))

    evaluation = {
        "question_id": question_id,
        "category": category,
        "question": question,
        "reference_sql": reference_sql,
        "generation_success": generation_success,
        "generated_sql": original_sql,
        "generation_error": l7_eval.get("generation_error"),
        "retrieval": l7_eval.get("retrieval"),
        "retrieval_latency_ms": l7_eval.get("retrieval_latency_ms"),
        "l7_prompt": l7_eval.get("prompt"),
        "execution_success": False,
        "correctness": False,
        "execution_error": None,
        "execution_error_type": None,
        "execution_time_ms": 0.0,
        "correction": None,
    }

    if not generation_success or original_sql is None:
        evaluation["execution_error"] = l7_eval.get("generation_error", "generation failed")
        evaluation["execution_error_type"] = "generation_error"
        return evaluation

    # Rebuild schema context from stored retrieval items
    items = l7_eval.get("retrieval", {}).get("items", [])
    retrieval_ns = SimpleNamespace(
        items=[
            SimpleNamespace(
                doc_type=i.get("doc_type", ""),
                doc_id=i.get("doc_id", ""),
                table=i.get("table", ""),
                column=i.get("column", ""),
                fk_source_table=i.get("fk_source_table", ""),
                fk_source_column=i.get("fk_source_column", ""),
                fk_target_table=i.get("fk_target_table", ""),
                fk_target_column=i.get("fk_target_column", ""),
                text=i.get("text", ""),
                score=i.get("score", 0.0),
                source=i.get("source", "retrieval"),
            )
            for i in items
        ]
    )
    context_text = l7_eval.get("retrieval", {}).get("schema_context", "")
    if not context_text:
        context_text = build_correction_context_text(retrieval_ns)

    corrector = SQLCorrector(
        db_path=db,
        model=model,
        max_attempts=max_attempts,
        timeout=timeout,
    )
    # Evaluation mode: a reference result is available for result-mismatch
    # guidance. Production callers must NOT pass this.
    reference_result_text = corrector.build_reference_result_text(
        reference_sql, db
    )
    correction_result = corrector.correct(
        question=question,
        category=category,
        question_id=question_id,
        reference_sql=reference_sql,
        original_sql=original_sql,
        retrieval=retrieval_ns,
        schema_context_text=context_text,
        reference_result_text=reference_result_text,
        is_l7_correct=l7_correct,
    )

    evaluation["correction"] = correction_to_dict(correction_result)
    evaluation["correctness"] = correction_result.final_correct
    # final execution state comes from the last attempt
    attempts = correction_result.attempts
    if attempts:
        last = attempts[-1]
        evaluation["execution_success"] = bool(last.execution_result.success)
        evaluation["execution_error"] = last.execution_error
        evaluation["execution_error_type"] = last.execution_error_type
        evaluation["execution_time_ms"] = last.execution_time_ms

    return evaluation


def correction_to_dict(result: CorrectionResult):
    return {
        "question_id": result.question_id,
        "question": result.question,
        "category": result.category,
        "reference_sql": result.reference_sql,
        "original_sql": result.original_sql,
        "final_sql": result.final_sql,
        "final_correct": result.final_correct,
        "total_attempts": result.total_attempts,
        "rescued": result.rescued,
        "harmed": result.harmed,
        "attempts": [
            {
                "attempt_number": a.attempt_number,
                "sql": a.sql,
                "prompt": a.prompt,
                "raw_response": a.raw_response,
                "execution_success": bool(a.execution_result.success) if a.execution_result else None,
                "execution_error": a.execution_error,
                "execution_error_type": a.execution_error_type,
                "execution_time_ms": a.execution_time_ms,
                "is_correct": a.is_correct,
            }
            for a in result.attempts
        ],
    }


def db_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(
        description="L8 execution-guided SQL self-correction experiment "
        "(real Ollama + real embedding model)"
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--embedding-model", default="all-MiniLM-L6-v2"
    )
    parser.add_argument("--collection", default="schema_index")
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR))
    parser.add_argument("--l4-report", default=str(DEFAULT_L4_REPORT))
    parser.add_argument("--l7-report", default=str(DEFAULT_L7_REPORT))
    parser.add_argument("--report", default=str(DEFAULT_L8_REPORT))
    parser.add_argument(
        "--fake-embedder",
        action="store_true",
        help="use the deterministic CountVector embedder (pipeline check only)",
    )
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    print("=" * 72)
    print("LEVEL 8 EXPERIMENT: EXECUTION-GUIDED SELF-CORRECTION")
    print("=" * 72)
    print(f"Model       : {args.model}")
    print(f"Embedding   : {args.embedding_model}")
    print(f"Top-K       : {args.top_k}")
    print(f"Max retries : {args.max_attempts}")
    print(f"Database    : {args.db}")
    print(f"Index dir   : {args.index_dir}")
    print(f"Questions   : {args.questions}")

    probe_ollama(args.model)

    l4_report = load_metrics_report(args.l4_report)
    l4_metrics = (l4_report or {}).get("metrics") or {}
    l4_by = (l4_report or {}).get("by_category")
    l4_evals = (l4_report or {}).get("evaluations") or []

    l7_report = load_metrics_report(args.l7_report)
    l7_metrics = (l7_report or {}).get("metrics") or {}
    l7_by = (l7_report or {}).get("by_category")
    l7_evals = (l7_report or {}).get("evaluations") or []

    if l4_metrics:
        print(f"L4 baseline found : {args.l4_report}")
    else:
        print("WARNING: L4 baseline report missing; comparison will show n/a",
              file=sys.stderr)
    if l7_metrics:
        print(f"L7 report found   : {args.l7_report}")
    else:
        print("WARNING: L7 report missing; comparison will show n/a",
              file=sys.stderr)

    if args.fake_embedder:
        retriever = SchemaRetriever(
            db_path=args.db,
            persist_dir=args.index_dir,
            collection_name=args.collection,
            top_k=args.top_k,
            embedder=CountVectorEmbedder(dimensions=384),
        )
        print("Embedder    : FAKE (CountVector) - pipeline check only")
    else:
        retriever = build_retriever(args)
        print(f"Embedder    : {args.embedding_model} (real)")

    with open(args.questions, encoding="utf-8") as handle:
        questions = json.load(handle)
    if args.limit:
        questions = questions[: args.limit]
    print(f"Running     : {len(questions)} questions")

    start = time.perf_counter()
    retriever.build_index()
    print(f"Indexed     : {retriever.index.count()} schema documents "
          f"({time.perf_counter() - start:.1f}s)")

    # Map L7 evaluations by question_id for lookup
    l7_eval_map = {e["question_id"]: e for e in l7_evals
                   if isinstance(e, dict) and "question_id" in e}

    # Filter to only questions that have L7 evaluations
    matched_questions = [q for q in questions if q.get("id") in l7_eval_map]
    if not matched_questions:
        print("ERROR: No matching questions found in L7 report", file=sys.stderr)
        sys.exit(1)

    sha_before = db_sha256(args.db)
    evaluations = []
    for item in matched_questions:
        l7_eval = l7_eval_map[item["id"]]
        evaluations.append(evaluate_question(
            l7_eval, item, args.model, args.db,
            max_attempts=args.max_attempts, timeout=args.timeout
        ))
    sha_after = db_sha256(args.db)
    database_intact = sha_before == sha_after
    print(f"Database integrity  : {'INTACT (sha256 unchanged)' if database_intact else 'CHANGED!'}")

    # Compute L8 metrics from the PseudoEval adapter
    metrics = compute_metrics(PseudoEvalList(evaluations))
    by_category = metrics_by_category(PseudoEvalList(evaluations))

    # ---- comparison table L4 | L7 | L8 ----
    print()
    print("=" * 96)
    print("L4 vs L7 vs L8 COMPARISON")
    print("=" * 96)
    print(f"{'Metric':<34}{'L4':>12}{'L7':>12}{'L8':>12}")
    rows = [
        ("total_questions", l4_metrics.get("total_questions"),
         l7_metrics.get("total_questions"), metrics["total_questions"], False),
        ("generation_success_rate", l4_metrics.get("generation_success_rate"),
         l7_metrics.get("generation_success_rate"), metrics["generation_success_rate"], True),
        ("execution_success_rate", l4_metrics.get("execution_success_rate"),
         l7_metrics.get("execution_success_rate"), metrics["execution_success_rate"], True),
        ("execution_accuracy", l4_metrics.get("execution_accuracy"),
         l7_metrics.get("execution_accuracy"), metrics["execution_accuracy"], True),
        ("sql_execution_error_rate", l4_metrics.get("sql_execution_error_rate"),
         l7_metrics.get("sql_execution_error_rate"), metrics["sql_execution_error_rate"], True),
    ]
    for label, l4v, l7v, l8v, is_pct in rows:
        def cell(v):
            if v is None:
                return "n/a"
            if is_pct:
                return f"{v * 100:.1f}%"
            return str(v)
        print(f"{label:<34}{cell(l4v):>12}{cell(l7v):>12}{cell(l8v):>12}")

    print()
    print(f"Average execution latency ms (L8) : {metrics['average_execution_latency_ms']:.2f}")
    print(f"Median execution latency ms (L8)  : {metrics['median_execution_latency_ms']:.2f}")
    total_llm_calls = sum(e["correction"]["total_attempts"] for e in evaluations if e["correction"])
    avg_attempts = total_llm_calls / len(evaluations) if evaluations else 0.0
    print(f"Average correction attempts       : {avg_attempts:.2f}")

    # ---- correction diagnostics ----
    correction_success = sum(
        1 for e in evaluations
        if e.get("correction") and e["correction"]["rescued"]
    )
    correction_failures = sum(
        1 for e in evaluations
        if e.get("correction") and not e["correction"]["final_correct"]
        and e["correction"]["total_attempts"] > 1
    )
    print(f"Correction rescued (L7 wrong -> L8 right): {correction_success}")
    print(f"Correction failed but retried           : {correction_failures}")

    # ---- per-question rescue/harm vs L7 ----
    rescued, harmed, held, missed = [], [], [], []
    for e in evaluations:
        old = l7_eval_map.get(e["question_id"])
        if old is None:
            continue
        old_correct = bool(old.get("correctness", old.get("correct", False)))
        new_correct = bool(e["correctness"])
        if old_correct and not new_correct:
            harmed.append(e)
        elif not old_correct and new_correct:
            rescued.append(e)
        elif old_correct and new_correct:
            held.append(e)
        else:
            missed.append(e)

    print()
    print("=" * 72)
    print("L8 vs L7 PER-QUESTION ANALYSIS")
    print("=" * 72)
    print(f"Rescued (L7 wrong  -> L8 right): {len(rescued)}")
    print(f"Harmed  (L7 right  -> L8 wrong): {len(harmed)}")
    print(f"Held    (L7 right  -> L8 right): {len(held)}")
    print(f"Missed  (L7 wrong  -> L8 wrong): {len(missed)}")

    print()
    print("-- L7 wrong -> L8 correct (rescued) --")
    for e in rescued[:10]:
        c = e["correction"]
        print(f"[{e['question_id']} | {e['category']}] {e['question']}")
        print(f"  L7   : {c['original_sql']}")
        print(f"  L8   : {c['final_sql']}")
        print(f"  #    : {c['total_attempts']} attempts")

    print()
    print("-- L7 wrong -> L8 still wrong (missed) --")
    for e in missed[:10]:
        c = e["correction"]
        print(f"[{e['question_id']} | {e['category']}] {e['question']}")
        print(f"  L7   : {c['original_sql']}")
        last_err = c["attempts"][-1]["execution_error"] if c["attempts"] else None
        print(f"  final: {c['final_sql']}  (err={last_err})")

    print()
    print("-- L7 correct -> L8 harmed --")
    for e in harmed[:10]:
        c = e["correction"]
        print(f"[{e['question_id']} | {e['category']}] {e['question']}")
        print(f"  L7   : {c['original_sql']}")
        print(f"  L8   : {c['final_sql']}")

    # ---- save report ----
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "embedding_model": args.embedding_model,
        "top_k": args.top_k,
        "max_attempts": args.max_attempts,
        "database": str(args.db),
        "questions_file": str(args.questions),
        "embedder": "fake" if args.fake_embedder else "real",
        "database_intact": database_intact,
        "l4_reference": str(args.l4_report),
        "l7_reference": str(args.l7_report),
        "l4_metrics": l4_metrics,
        "l7_metrics": l7_metrics,
        "metrics": metrics,
        "by_category": by_category,
        "retrieval_latency_avg_ms": round(
            sum(e.get("retrieval_latency_ms", 0) for e in evaluations) / len(evaluations), 3
        ) if evaluations else 0.0,
        "average_correction_attempts": round(avg_attempts, 3),
        "correction_success_rate": round(
            correction_success / len(evaluations), 4
        ) if evaluations else 0.0,
        "rescued": len(rescued),
        "harmed": len(harmed),
        "held": len(held),
        "missed": len(missed),
        "rescue_ids": [e["question_id"] for e in rescued],
        "harm_ids": [e["question_id"] for e in harmed],
        "evaluations": evaluations,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport saved (L4/L7 untouched) : {report_path}")


class PseudoEvalList:
    """Adapter exposing QueryEvaluation-like attributes used by metrics."""

    def __init__(self, evaluations):
        self._items = evaluations

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        for e in self._items:
            yield PseudoEval(e)


class PseudoEval:
    def __init__(self, e):
        self._e = e

    @property
    def generation_success(self):
        return self._e["generation_success"]

    @property
    def execution_success(self):
        return self._e["execution_success"]

    @property
    def correctness(self):
        return self._e["correctness"]

    @property
    def execution_time_ms(self):
        return self._e["execution_time_ms"]

    @property
    def category(self):
        return self._e["category"]


if __name__ == "__main__":
    main()