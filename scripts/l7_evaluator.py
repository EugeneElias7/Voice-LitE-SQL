"""Voice-LitE-SQL -- L7 experiment: retrieval-augmented schema linking.

Runs the SAME 50 clean questions from questions.json through the L7
pipeline::

    Question -> SchemaRetriever (ChromaDB, top-K) -> L7 prompt
              -> Qwen (same model as L4) -> execute -> compare

and compares directly against the frozen L4 baseline
(evaluation/results/l4_report.json -- never overwritten).

The ONLY intervention vs L4 is schema retrieval + schema-grounded prompting.
L4 code, model, database, executor and evaluation methodology are unchanged.

Usage:
    python scripts/l7_evaluator.py
    python scripts/l7_evaluator.py --limit 10 --top-k 8 --model qwen2.5-coder:1.5b

Exits with a clear error if Ollama is unavailable (no mock substitution).
Also exits if the real embedding model is unavailable for the real run.
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database.executor import execute_sql  # noqa: E402
from backend.evaluation.evaluator import results_equal  # noqa: E402
from backend.evaluation.metrics import compute_metrics, metrics_by_category  # noqa: E402
from backend.llm.ollama_client import DEFAULT_MODEL, OllamaError, generate  # noqa: E402
from backend.llm.sql_generator import extract_sql, validate_read_only  # noqa: E402
from backend.retrieval import (  # noqa: E402
    CountVectorEmbedder,
    EmbeddingError,
    SchemaRetriever,
    SentenceTransformerEmbedder,
    build_l7_prompt,
)
from backend.retrieval.embeddings import EMBEDDING_DIMENSIONS  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "backend" / "data" / "enterprise.db"
DEFAULT_QUESTIONS = PROJECT_ROOT / "backend" / "datasets" / "custom" / "questions.json"
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
DEFAULT_L4_REPORT = RESULTS_DIR / "l4_report.json"
DEFAULT_L7_REPORT = RESULTS_DIR / "l7_report.json"
DEFAULT_INDEX_DIR = PROJECT_ROOT / "evaluation" / "index" / "l7"

CATEGORY_ORDER = [
    "SELECT",
    "WHERE",
    "JOIN",
    "GROUP BY",
    "ORDER BY",
    "aggregate",
    "complex",
]


def load_l4_baseline(path):
    """Return the frozen L4 metrics for comparison (never modified)."""
    if not Path(path).exists():
        return None
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
            "The real L7 run requires the embedding model available locally. "
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


def generate_l7(question, retriever, model):
    """One L7 generation: retrieve schema -> build prompt -> Qwen -> SQL."""
    started = time.perf_counter()
    retrieval = retriever.retrieve(question)
    retrieval_latency_ms = (time.perf_counter() - started) * 1000.0

    prompt = build_l7_prompt(question, retrieval.schema_context_text)
    try:
        raw_response, _ = generate(prompt, model=model)
    except OllamaError as exc:
        return {
            "generation_success": False,
            "generated_sql": None,
            "error": f"ollama error: {exc}",
            "raw_prompt": prompt,
            "retrieval": retrieval.to_dict(),
            "retrieval_latency_ms": round(retrieval_latency_ms, 3),
        }

    try:
        sql = extract_sql(raw_response)
        validate_read_only(sql)
    except ValueError as exc:
        return {
            "generation_success": False,
            "generated_sql": None,
            "error": f"sql extraction failed: {exc}",
            "raw_prompt": prompt,
            "raw_response": raw_response,
            "retrieval": retrieval.to_dict(),
            "retrieval_latency_ms": round(retrieval_latency_ms, 3),
        }

    return {
        "generation_success": True,
        "generated_sql": sql,
        "error": None,
        "raw_prompt": prompt,
        "retrieval": retrieval.to_dict(),
        "retrieval_latency_ms": round(retrieval_latency_ms, 3),
    }


def evaluate_question(item, retriever, model, db):
    """Evaluate one question item under the L7 pipeline."""
    question = item["question"]

    gen = generate_l7(question, retriever, model)
    evaluation = {
        "question_id": item.get("id", ""),
        "category": item.get("category", ""),
        "question": question,
        "reference_sql": item.get("sql", ""),
        "generation_success": gen["generation_success"],
        "generated_sql": gen["generated_sql"],
        "generation_error": gen["error"],
        "retrieval": gen["retrieval"],
        "retrieval_latency_ms": gen["retrieval_latency_ms"],
        "prompt": gen["raw_prompt"],
        "execution_success": False,
        "correctness": False,
        "execution_error": None,
        "execution_error_type": None,
        "execution_time_ms": 0.0,
    }

    if not gen["generation_success"]:
        evaluation["execution_error"] = gen["error"]
        evaluation["execution_error_type"] = "generation_error"
        return evaluation

    executed = execute_sql(gen["generated_sql"], db)
    evaluation["execution_time_ms"] = executed.execution_time_ms
    if not executed.success:
        evaluation["execution_error"] = executed.error
        evaluation["execution_error_type"] = executed.error_type
        return evaluation

    reference = execute_sql(item["sql"], db)
    evaluation["execution_success"] = True
    if reference.success:
        evaluation["correctness"] = results_equal(
            item["sql"], reference, gen["generated_sql"], executed
        )
    return evaluation


def db_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metric_line(label, l4, l7):
    l4v = l4.get(label) if l4 else None
    l7v = l7.get(label) if l7 else None
    l4s = "n/a" if l4v is None else f"{l4v * 100:.1f}%"
    l7s = "n/a" if l7v is None else f"{l7v * 100:.1f}%"
    diff = "" if (l4v is None or l7v is None) else f"{l7v - l4v:+.1%}"
    return f"{label:<32}{l4s:>12}{l7s:>12}{diff:>12}"


def print_comparison(l4_meta, l4_metrics, l7_metrics):
    print("=" * 72)
    print("L7 vs L4 BASELINE COMPARISON")
    print("=" * 72)
    print(f"{'Metric':<32}{'L4 Baseline':>12}{'L7 Retrieval':>12}{'Diff':>12}")
    for label in (
        "total_questions",
        "generation_success_rate",
        "execution_success_rate",
        "execution_accuracy",
        "sql_execution_error_rate",
    ):
        if label == "total_questions":
            l4s = str(l4_metrics["total_questions"]) if l4_metrics else "n/a"
            l7s = str(l7_metrics["total_questions"])
            print(f"{label:<32}{l4s:>12}{l7s:>12}")
            continue
        print(metric_line(label, l4_metrics, l7_metrics))
    print(
        metric_line("sql_exe_error_rate(L7 ref)", None, l7_metrics)
    )
    print()


def print_category_comparison(l4_by, l7_by):
    print("=" * 72)
    print("CATEGORY-LEVEL COMPARISON (execution accuracy)")
    print("=" * 72)
    print(f"{'Category':<12}{'L4 %':>10}{'L7 %':>10}{'Diff':>10}{'N':>6}")
    for category in CATEGORY_ORDER:
        l4 = (l4_by or {}).get(category) or {}
        l7 = l7_by.get(category) or {}
        l4a = l4.get("execution_accuracy")
        l7a = l7.get("execution_accuracy")
        n = l7.get("total_questions", l4.get("total_questions", 0))
        l4s = "n/a" if l4a is None else f"{l4a * 100:.1f}"
        l7s = "n/a" if l7a is None else f"{l7a * 100:.1f}"
        diff = "" if (l4a is None or l7a is None) else f"{l7a - l4a:+.1f}"
        print(f"{category:<12}{l4s:>10}{l7s:>10}{diff:>10}{n:>6}")


def print_examples(evaluations, resolved, missed):
    print()
    print("=" * 72)
    print("WHERE RETRIEVAL HELPED / FAILED")
    print("=" * 72)
    print("-- L4 incorrect -> L7 correct (retrieval fixed a hallucination) --")
    for e in resolved[:3]:
        print(f"[{e['question_id']} | {e['category']}] {e['question']}")
        print(f"  L7 SQL : {e['generated_sql']}")
        print(f"  Retr   : {len(e['retrieval']['items'])} items")
        for item in e["retrieval"]["items"][:3]:
            print(f"    - {item['doc_id'][:60]} (score {item['score']:.3f})")
    print()
    print("-- L4 correct -> L7 incorrect/error (retrieval missed) --")
    for e in missed[:3]:
        print(f"[{e['question_id']} | {e['category']}] {e['question']}")
        print(f"  L7 SQL : {e['generated_sql']}")
        print(f"  Error  : {e['execution_error']}")
        print(f"  Retr   : {len(e['retrieval']['items'])} items")
        for item in e["retrieval"]["items"][:3]:
            print(f"    - {item['doc_id'][:60]} (score {item['score']:.3f})")


def main():
    parser = argparse.ArgumentParser(
        description="L7 schema-retrieval experiment (real Ollama + real embedding model)"
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
    parser.add_argument("--report", default=str(DEFAULT_L7_REPORT))
    parser.add_argument(
        "--fake-embedder",
        action="store_true",
        help="use the deterministic CountVector embedder (pipeline check only)",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("LEVEL 7 EXPERIMENT: SCHEMA RETRIEVAL")
    print("=" * 72)
    print(f"Model       : {args.model}")
    print(f"Embedding   : {args.embedding_model}")
    print(f"Top-K       : {args.top_k}")
    print(f"Database    : {args.db}")
    print(f"Index dir   : {args.index_dir}")
    print(f"Questions   : {args.questions}")

    probe_ollama(args.model)
    l4 = load_l4_baseline(args.l4_report)
    if l4 is None:
        print(
            f"WARNING: L4 baseline report not found at {args.l4_report}. "
            "Running L7 standalone; comparison will show 'n/a'.",
            file=sys.stderr,
        )

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

    # Reuse the real (unmodified) L4 read-only executor for evaluation.
    _ = execute_sql  # explicit: L4 executor is the evaluation executor

    evaluations = [
        evaluate_question(item, retriever, args.model, args.db)
        for item in questions
    ]

    metrics = compute_metrics(PseudoEvalList(evaluations))
    by_category = metrics_by_category(PseudoEvalList(evaluations))

    l4_meta = l4 or {}
    l4_metrics = l4_meta.get("metrics") or {}
    l4_by = l4_meta.get("by_category")

    print_comparison(l4_meta, l4_metrics, metrics)
    print_category_comparison(l4_by, by_category)

    # retrieval diagnostics
    retrieval_lat = [
        e["retrieval_latency_ms"] for e in evaluations if e["retrieval_latency_ms"]
    ]
    avg_retrieval = sum(retrieval_lat) / len(retrieval_lat) if retrieval_lat else 0.0
    avg_retrieved = (
        sum(len(e["retrieval"]["items"]) for e in evaluations) / len(evaluations)
        if evaluations
        else 0.0
    )
    print()
    print(f"Average retrieval latency ms : {avg_retrieval:.1f}")
    print(f"Average retrieved items      : {avg_retrieved:.1f}")

    # rescue / harm analysis vs L4
    if l4_metrics:
        l4_eval_map = {e["question_id"]: e for e in l4_meta.get("evaluations", [])}
        resolved, missed, harmed, helped = [], [], [], []
        for e in evaluations:
            old = l4_eval_map.get(e["question_id"])
            if old is None:
                continue
            old_correct = bool(old["correctness"])
            new_correct = bool(e["correctness"])
            if old_correct and not new_correct:
                harmed.append(e)
            if not old_correct and new_correct:
                resolved.append(e)
            if old_correct and new_correct:
                helped.append(e)
            if not old_correct and not new_correct:
                missed.append(e)
        print()
        print(f"Rescued (L4 wrong  -> L7 right): {len(resolved)}")
        print(f"Harmed  (L4 right  -> L7 wrong): {len(harmed)}")
        print(f"Held    (L4 right  -> L7 right): {len(helped)}")
        print(f"Missed  (L4 wrong  -> L7 wrong): {len(missed)}")
        print_examples(evaluations, resolved, missed)

    # save report (never touches l4_report.json)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "embedding_model": args.embedding_model,
        "top_k": args.top_k,
        "database": str(args.db),
        "questions_file": str(args.questions),
        "embedder": "fake" if args.fake_embedder else "real",
        "l4_reference": str(args.l4_report),
        "l4_metrics": l4_metrics,
        "metrics": metrics,
        "by_category": by_category,
        "retrieval_latency_avg_ms": round(avg_retrieval, 3),
        "average_retrieved_items": round(avg_retrieved, 3),
        "evaluations": evaluations,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report saved (L4 untouched) : {report_path}")


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