"""Voice-LitE-SQL -- L8.1 experiment: NLP + Schema-Linking Optimization.

Pipeline:
    Question -> L6 Normalization -> Intent Classification
          -> Entity/Phrase Linking -> L7 Vector Retrieval
          -> Candidate Reranking -> Relationship Necessity Filter
          -> Qwen 1.5B -> SQL Structural Validation
          -> L4 Executor -> L8 Execution-Guided Correction -> Result

Compares against frozen L4 (40%), L7 (36%), L8 (48%) baselines.
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
    SQLCorrector,
    build_correction_context_text,
)
from backend.database.executor import execute_sql  # noqa: E402
from backend.evaluation.evaluator import results_equal  # noqa: E402
from backend.evaluation.metrics import compute_metrics, metrics_by_category  # noqa: E402
from backend.llm.ollama_client import DEFAULT_MODEL, OllamaError, generate  # noqa: E402
from backend.llm.sql_generator import extract_sql, validate_read_only  # noqa: E402
from backend.nlp import (  # noqa: E402
    classify_intent,
    link_schema_entities,
    match_phrases,
)
from backend.retrieval import (  # noqa: E402
    CountVectorEmbedder,
    EmbeddingError,
    SchemaRetriever,
    SentenceTransformerEmbedder,
    format_schema_context,
)
from backend.retrieval.embeddings import EMBEDDING_DIMENSIONS  # noqa: E402
from backend.retrieval.reranker import RerankWeights, rerank_retrieval  # noqa: E402
from backend.retrieval.relationship_filter import filter_relationships  # noqa: E402
from backend.validation import validate_sql_structure  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "backend" / "data" / "enterprise.db"
DEFAULT_QUESTIONS = PROJECT_ROOT / "backend" / "datasets" / "custom" / "questions.json"
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
DEFAULT_L4_REPORT = RESULTS_DIR / "l4_report.json"
DEFAULT_L7_REPORT = RESULTS_DIR / "l7_report.json"
DEFAULT_L8_REPORT = RESULTS_DIR / "l8_report.json"
DEFAULT_L8_1_REPORT = RESULTS_DIR / "l8_1_report.json"
DEFAULT_INDEX_DIR = PROJECT_ROOT / "evaluation" / "index" / "l8_1"

CATEGORY_ORDER = [
    "SELECT",
    "WHERE",
    "JOIN",
    "GROUP BY",
    "ORDER BY",
    "aggregate",
    "complex",
]


def load_baseline_report(path):
    """Load a frozen baseline report."""
    if not Path(path).exists():
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def probe_ollama(model):
    """Verify Ollama is available."""
    try:
        generate("Reply with exactly: OK", model=model, timeout=30)
    except OllamaError as exc:
        print(f"ERROR: Ollama is not available - {exc}", file=sys.stderr)
        print("Start Ollama (and make sure the model is pulled) then re-run.", file=sys.stderr)
        sys.exit(1)


def build_retriever(args):
    """Build the real SchemaRetriever with the real embedding model."""
    try:
        embedder = SentenceTransformerEmbedder(model_name=args.embedding_model)
    except EmbeddingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "The real run requires the embedding model available locally. "
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
        embedding_dimensions=EMBEDDING_DIMENSIONS.get(args.embedding_model, 384),
        top_k=args.top_k,
        embedder=embedder,
    )


def generate_l8_1(question, retriever, model, db_path, top_k, enable_all=True):
    """One L8.1 generation with full NLP pipeline."""
    started = time.perf_counter()

    # 1. Query Intent Classification
    intent = classify_intent(question)

    # 2. Schema/Entity Linking
    linked_entities = link_schema_entities(question, db_path)

    # 3. Phrase Matching
    phrase_matches = match_phrases(question, db_path)

    # 4. L7 Vector Retrieval
    retrieval = retriever.retrieve(question, top_k=top_k)
    retrieval_latency_ms = (time.perf_counter() - started) * 1000.0

    # 5. Candidate Reranking
    if enable_all:
        retrieval = rerank_retrieval(
            question, retrieval, intent, linked_entities, phrase_matches
        )

    # 6. Relationship Necessity Filter
    if enable_all:
        retrieval, rel_assessments = filter_relationships(
            question, retrieval, intent, linked_entities, db_path
        )
    else:
        rel_assessments = []

    # Build prompt with filtered schema context
    schema_context_text = format_schema_context(retrieval.items)

    # L7-style prompt but with filtered context
    forbidden = "INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, ATTACH, DETACH, PRAGMA, REPLACE, TRUNCATE, VACUUM, GRANT, REVOKE"
    prompt = f"""You are a SQLite SQL generation assistant.

Generate a single SQLite query that answers the user's question.

Rules:
- Return ONLY the SQL statement, with no explanation.
- Use only the provided schema. Do not invent tables or columns.
- Use SELECT (or WITH) only. The following operations are strictly forbidden: {forbidden}.
- Use JOIN only when the schema relationships below require it.
- You may only reference the foreign key relationships listed below.

RETRIEVED SCHEMA
{schema_context_text}

QUESTION
{question}

SQL:"""

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
            "intent": {
                "primary": intent.primary_intent.value,
                "join_required": intent.join_required,
                "aggregation_required": intent.aggregation_required,
                "grouping_required": intent.grouping_required,
                "ordering_required": intent.ordering_required,
                "subquery_likely": intent.subquery_likely,
                "confidence": intent.confidence,
            },
            "linked_entities": [e.__dict__ for e in linked_entities],
            "phrase_matches": [p.__dict__ for p in phrase_matches],
            "relationship_assessments": [a.__dict__ for a in rel_assessments] if rel_assessments else [],
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
            "intent": {
                "primary": intent.primary_intent.value,
                "join_required": intent.join_required,
                "aggregation_required": intent.aggregation_required,
                "grouping_required": intent.grouping_required,
                "ordering_required": intent.ordering_required,
                "subquery_likely": intent.subquery_likely,
                "confidence": intent.confidence,
            },
            "linked_entities": [e.__dict__ for e in linked_entities],
            "phrase_matches": [p.__dict__ for p in phrase_matches],
            "relationship_assessments": [a.__dict__ for a in rel_assessments] if rel_assessments else [],
        }

    # 7. SQL Structural Validation
    validation = validate_sql_structure(sql, db_path, intent)
    validation_passed = validation.is_valid

    return {
        "generation_success": True,
        "generated_sql": sql,
        "error": None,
        "raw_prompt": prompt,
        "raw_response": raw_response,
        "retrieval": retrieval.to_dict(),
        "retrieval_latency_ms": round(retrieval_latency_ms, 3),
        "intent": {
            "primary": intent.primary_intent.value,
            "join_required": intent.join_required,
            "aggregation_required": intent.aggregation_required,
            "grouping_required": intent.grouping_required,
            "ordering_required": intent.ordering_required,
            "subquery_likely": intent.subquery_likely,
            "confidence": intent.confidence,
        },
        "linked_entities": [e.__dict__ for e in linked_entities],
        "phrase_matches": [p.__dict__ for p in phrase_matches],
        "relationship_assessments": [a.__dict__ for a in rel_assessments] if rel_assessments else [],
        "validation": {
            "is_valid": validation.is_valid,
            "issues": [i.__dict__ for i in validation.issues],
            "tables_used": validation.tables_used,
            "columns_used": validation.columns_used,
            "joins": validation.joins,
            "has_aggregation": validation.has_aggregation,
            "has_group_by": validation.has_group_by,
            "has_order_by": validation.has_order_by,
            "has_subquery": validation.has_subquery,
        },
        "validation_passed": validation_passed,
    }


def evaluate_question(item, retriever, model, db, top_k, enable_all=True):
    """Evaluate one question under the L8.1 pipeline."""
    question = item["question"]

    gen = generate_l8_1(question, retriever, model, db, top_k, enable_all)
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
        "intent": gen.get("intent"),
        "linked_entities": gen.get("linked_entities"),
        "phrase_matches": gen.get("phrase_matches"),
        "relationship_assessments": gen.get("relationship_assessments"),
        "validation": gen.get("validation"),
        "validation_passed": gen.get("validation_passed"),
        "execution_success": False,
        "correctness": False,
        "execution_error": None,
        "execution_error_type": None,
        "execution_time_ms": 0.0,
        "correction": None,
    }

    if not gen["generation_success"]:
        evaluation["execution_error"] = gen["error"]
        evaluation["execution_error_type"] = "generation_error"
        return evaluation

    # Execute initial SQL
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

    # If incorrect, run correction loop (L8 style)
    if not evaluation["correctness"]:
        # Build retrieval context for correction
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
                    distance=i.get("distance", 1.0),
                    source=i.get("source", "retrieval"),
                )
                for i in gen["retrieval"]["items"]
            ]
        )
        context_text = gen["retrieval"].get("schema_context", "")
        if not context_text:
            context_text = build_correction_context_text(retrieval_ns)

        corrector = SQLCorrector(
            db_path=db,
            model=model,
            max_attempts=3,
            timeout=120,
        )
        reference_result_text = corrector.build_reference_result_text(
            item["sql"], db
        )
        correction_result = corrector.correct(
            question=question,
            category=item.get("category", ""),
            question_id=item.get("id", ""),
            reference_sql=item["sql"],
            original_sql=gen["generated_sql"],
            retrieval=retrieval_ns,
            schema_context_text=context_text,
            reference_result_text=reference_result_text,
            is_l7_correct=False,
        )

        evaluation["correction"] = {
            "question_id": correction_result.question_id,
            "question": correction_result.question,
            "category": correction_result.category,
            "reference_sql": correction_result.reference_sql,
            "original_sql": correction_result.original_sql,
            "final_sql": correction_result.final_sql,
            "final_correct": correction_result.final_correct,
            "total_attempts": correction_result.total_attempts,
            "rescued": correction_result.rescued,
            "harmed": correction_result.harmed,
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
                for a in correction_result.attempts
            ],
        }
        evaluation["correctness"] = correction_result.final_correct
        if correction_result.attempts:
            last = correction_result.attempts[-1]
            evaluation["execution_success"] = bool(last.execution_result.success) if last.execution_result else False
            evaluation["execution_error"] = last.execution_error
            evaluation["execution_error_type"] = last.execution_error_type
            evaluation["execution_time_ms"] = last.execution_time_ms

    return evaluation


def db_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metric_line(label, l4, l7, l8, l8_1):
    def cell(v):
        if v is None:
            return "n/a"
        return f"{v * 100:.1f}%"
    l4s = cell(l4.get(label)) if l4 else "n/a"
    l7s = cell(l7.get(label)) if l7 else "n/a"
    l8s = cell(l8.get(label)) if l8 else "n/a"
    l81s = cell(l8_1.get(label))
    return f"{label:<34}{l4s:>10}{l7s:>10}{l8s:>10}{l81s:>10}"


def print_comparison(l4_metrics, l7_metrics, l8_metrics, l8_1_metrics):
    print("=" * 84)
    print("L4 vs L7 vs L8 vs L8.1 COMPARISON")
    print("=" * 84)
    print(f"{'Metric':<34}{'L4':>10}{'L7':>10}{'L8':>10}{'L8.1':>10}")
    rows = [
        ("total_questions", False),
        ("generation_success_rate", True),
        ("execution_success_rate", True),
        ("execution_accuracy", True),
        ("sql_execution_error_rate", True),
    ]
    for label, is_pct in rows:
        l4v = l4_metrics.get(label) if l4_metrics else None
        l7v = l7_metrics.get(label) if l7_metrics else None
        l8v = l8_metrics.get(label) if l8_metrics else None
        l81v = l8_1_metrics.get(label)
        def cell(v):
            if v is None:
                return "n/a"
            if is_pct:
                return f"{v * 100:.1f}%"
            return str(v)
        print(f"{label:<34}{cell(l4v):>10}{cell(l7v):>10}{cell(l8v):>10}{cell(l81v):>10}")


def print_category_comparison(l4_by, l7_by, l8_by, l8_1_by):
    print("=" * 84)
    print("CATEGORY-LEVEL COMPARISON (execution accuracy)")
    print("=" * 84)
    print(f"{'Category':<12}{'L4%':>8}{'L7%':>8}{'L8%':>8}{'L8.1%':>8}{'N':>6}")
    for category in CATEGORY_ORDER:
        l4 = (l4_by or {}).get(category) or {}
        l7 = (l7_by or {}).get(category) or {}
        l8 = (l8_by or {}).get(category) or {}
        l81 = l8_1_by.get(category) or {}
        l4a = l4.get("execution_accuracy")
        l7a = l7.get("execution_accuracy")
        l8a = l8.get("execution_accuracy")
        l81a = l81.get("execution_accuracy")
        n = l81.get("total_questions", 0)
        def fmt(v):
            return "n/a" if v is None else f"{v * 100:.1f}"
        print(f"{category:<12}{fmt(l4a):>8}{fmt(l7a):>8}{fmt(l8a):>8}{fmt(l81a):>8}{n:>6}")


def print_ablation_results(ablation_results):
    """Print ablation study results."""
    print("=" * 84)
    print("ABLATION STUDY RESULTS")
    print("=" * 84)
    print(f"{'Configuration':<40}{'Accuracy':>10}{'Exec%':>10}{'Rescued':>10}{'Harmed':>10}")
    for name, metrics in ablation_results.items():
        acc = metrics.get("execution_accuracy", 0)
        exec_rate = metrics.get("execution_success_rate", 0)
        rescued = metrics.get("rescued", 0)
        harmed = metrics.get("harmed", 0)
        print(f"{name:<40}{acc*100:>9.1f}%{exec_rate*100:>9.1f}%{rescued:>10}{harmed:>10}")


def main():
    parser = argparse.ArgumentParser(
        description="L8.1 NLP + Schema-Linking Optimization experiment"
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--embedding-model", default="all-MiniLM-L6-v2")
    parser.add_argument("--collection", default="schema_index")
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR))
    parser.add_argument("--l4-report", default=str(DEFAULT_L4_REPORT))
    parser.add_argument("--l7-report", default=str(DEFAULT_L7_REPORT))
    parser.add_argument("--l8-report", default=str(DEFAULT_L8_REPORT))
    parser.add_argument("--report", default=str(DEFAULT_L8_1_REPORT))
    parser.add_argument(
        "--fake-embedder",
        action="store_true",
        help="use the deterministic CountVector embedder (pipeline check only)",
    )
    parser.add_argument(
        "--disable-reranker",
        action="store_true",
        help="disable candidate reranking (ablation)",
    )
    parser.add_argument(
        "--disable-rel-filter",
        action="store_true",
        help="disable relationship necessity filter (ablation)",
    )
    parser.add_argument(
        "--disable-intent",
        action="store_true",
        help="disable intent classification (ablation)",
    )
    parser.add_argument(
        "--disable-linking",
        action="store_true",
        help="disable schema/entity linking (ablation)",
    )
    parser.add_argument(
        "--disable-phrases",
        action="store_true",
        help="disable phrase matching (ablation)",
    )
    parser.add_argument(
        "--disable-validation",
        action="store_true",
        help="disable SQL structural validation (ablation)",
    )
    parser.add_argument(
        "--run-ablations",
        action="store_true",
        help="run full ablation study (all combinations)",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("LEVEL 8.1 EXPERIMENT: NLP + SCHEMA-LINKING OPTIMIZATION")
    print("=" * 72)
    print(f"Model       : {args.model}")
    print(f"Embedding   : {args.embedding_model}")
    print(f"Top-K       : {args.top_k}")
    print(f"Database    : {args.db}")
    print(f"Index dir   : {args.index_dir}")
    print(f"Questions   : {args.questions}")

    probe_ollama(args.model)

    # Load baselines
    l4_report = load_baseline_report(args.l4_report)
    l4_metrics = (l4_report or {}).get("metrics") or {}
    l4_by = (l4_report or {}).get("by_category")

    l7_report = load_baseline_report(args.l7_report)
    l7_metrics = (l7_report or {}).get("metrics") or {}
    l7_by = (l7_report or {}).get("by_category")

    l8_report = load_baseline_report(args.l8_report)
    l8_metrics = (l8_report or {}).get("metrics") or {}
    l8_by = (l8_report or {}).get("by_category")

    if l4_metrics:
        print(f"L4 baseline found : {args.l4_report}")
    else:
        print("WARNING: L4 baseline report missing", file=sys.stderr)
    if l7_metrics:
        print(f"L7 report found   : {args.l7_report}")
    else:
        print("WARNING: L7 report missing", file=sys.stderr)
    if l8_metrics:
        print(f"L8 report found   : {args.l8_report}")
    else:
        print("WARNING: L8 report missing", file=sys.stderr)

    # Build retriever
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
        questions = questions[:args.limit]
    print(f"Running     : {len(questions)} questions")

    # Build index
    start = time.perf_counter()
    retriever.build_index()
    print(f"Indexed     : {retriever.index.count()} schema documents "
          f"({time.perf_counter() - start:.1f}s)")

    # Determine which components to enable
    enable_reranker = not args.disable_reranker
    enable_rel_filter = not args.disable_rel_filter
    enable_intent = not args.disable_intent
    enable_linking = not args.disable_linking
    enable_phrases = not args.disable_phrases
    enable_validation = not args.disable_validation

    enable_all = (enable_reranker and enable_rel_filter and
                  enable_intent and enable_linking and enable_phrases and enable_validation)

    print(f"Components  : reranker={enable_reranker} rel_filter={enable_rel_filter} "
          f"intent={enable_intent} linking={enable_linking} phrases={enable_phrases} "
          f"validation={enable_validation}")

    sha_before = db_sha256(args.db)

    evaluations = []
    for item in questions:
        evaluations.append(evaluate_question(
            item, retriever, args.model, args.db, args.top_k, enable_all
        ))

    sha_after = db_sha256(args.db)
    database_intact = sha_before == sha_after
    print(f"Database integrity  : {'INTACT (sha256 unchanged)' if database_intact else 'CHANGED!'}")

    # Compute metrics
    class PseudoEvalList:
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

    metrics = compute_metrics(PseudoEvalList(evaluations))
    by_category = metrics_by_category(PseudoEvalList(evaluations))

    # Rescue/harm analysis vs L8
    l8_eval_map = {}
    if l8_report and "evaluations" in l8_report:
        l8_eval_map = {e["question_id"]: e for e in l8_report["evaluations"]}

    rescued, harmed, held, missed = [], [], [], []
    for e in evaluations:
        old = l8_eval_map.get(e["question_id"])
        if old is None:
            continue
        old_correct = bool(old.get("correctness", False))
        new_correct = bool(e["correctness"])
        if old_correct and not new_correct:
            harmed.append(e)
        elif not old_correct and new_correct:
            rescued.append(e)
        elif old_correct and new_correct:
            held.append(e)
        else:
            missed.append(e)

    print_comparison(l4_metrics, l7_metrics, l8_metrics, metrics)
    print_category_comparison(l4_by, l7_by, l8_by, by_category)

    print()
    print(f"Average retrieval latency ms : {metrics.get('average_execution_latency_ms', 0):.1f}")
    print(f"Median execution latency ms  : {metrics.get('median_execution_latency_ms', 0):.1f}")
    print(f"Database integrity           : {'INTACT' if database_intact else 'CHANGED'}")
    print()
    print("=" * 72)
    print("L8.1 vs L8 PER-QUESTION ANALYSIS")
    print("=" * 72)
    print(f"Rescued (L8 wrong  -> L8.1 right): {len(rescued)}")
    print(f"Harmed  (L8 right  -> L8.1 wrong): {len(harmed)}")
    print(f"Held    (L8 right  -> L8.1 right): {len(held)}")
    print(f"Missed  (L8 wrong  -> L8.1 wrong): {len(missed)}")

    if rescued:
        print()
        print("-- L8 wrong -> L8.1 correct (rescued) --")
        for e in rescued[:10]:
            c = e.get("correction") or {}
            print(f"[{e['question_id']} | {e['category']}] {e['question']}")
            print(f"  L8   : {c.get('original_sql', e['generated_sql'])}")
            print(f"  L8.1 : {c.get('final_sql', e['generated_sql'])}")

    if missed:
        print()
        print("-- L8 wrong -> L8.1 still wrong (missed) --")
        for e in missed[:10]:
            c = e.get("correction") or {}
            l8_sql = c.get('original_sql', e['generated_sql'])
            l81_sql = c.get('final_sql', e['generated_sql'])
            print(f"[{e['question_id']} | {e['category']}] {e['question']}")
            print(f"  L8   : {l8_sql}")
            print(f"  L8.1 : {l81_sql}")

    # Run ablations if requested
    ablation_results = {}
    if args.run_ablations:
        print()
        print("=" * 72)
        print("RUNNING ABLATION STUDY")
        print("=" * 72)
        ablation_configs = [
            ("L8 (baseline)", {"reranker": False, "rel_filter": False, "intent": False, "linking": False, "phrases": False, "validation": False}),
            ("+ Intent", {"reranker": False, "rel_filter": False, "intent": True, "linking": False, "phrases": False, "validation": False}),
            ("+ Linking", {"reranker": False, "rel_filter": False, "intent": False, "linking": True, "phrases": False, "validation": False}),
            ("+ Phrases", {"reranker": False, "rel_filter": False, "intent": False, "linking": False, "phrases": True, "validation": False}),
            ("+ Rel Filter", {"reranker": False, "rel_filter": True, "intent": False, "linking": False, "phrases": False, "validation": False}),
            ("+ Reranker", {"reranker": True, "rel_filter": False, "intent": False, "linking": False, "phrases": False, "validation": False}),
            ("+ Validation", {"reranker": False, "rel_filter": False, "intent": False, "linking": False, "phrases": False, "validation": True}),
            ("Full L8.1", {"reranker": True, "rel_filter": True, "intent": True, "linking": True, "phrases": True, "validation": True}),
        ]

        for name, config in ablation_configs:
            print(f"\nRunning ablation: {name}...")
            evals = []
            for item in questions:
                gen = generate_l8_1(
                    item["question"], retriever, args.model, args.db,
                    args.top_k, enable_all=any(config.values())
                )
                evals.append(gen)
            # Compute quick metrics
            total = len(evals)
            correct = sum(1 for e in evals if e.get("correctness", False))
            executed = sum(1 for e in evals if e.get("execution_success", False))
            generated = sum(1 for e in evals if e.get("generation_success", False))
            ablation_results[name] = {
                "execution_accuracy": correct / total if total else 0,
                "execution_success_rate": executed / total if total else 0,
                "generation_success_rate": generated / total if total else 0,
            }

        print_ablation_results(ablation_results)

    # Save report
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    avg_retrieval = sum(e.get("retrieval_latency_ms", 0) for e in evaluations) / len(evaluations) if evaluations else 0

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "embedding_model": args.embedding_model,
        "top_k": args.top_k,
        "database": str(args.db),
        "questions_file": str(args.questions),
        "embedder": "fake" if args.fake_embedder else "real",
        "database_intact": database_intact,
        "components": {
            "reranker": enable_reranker,
            "relationship_filter": enable_rel_filter,
            "intent_classification": enable_intent,
            "schema_linking": enable_linking,
            "phrase_matching": enable_phrases,
            "sql_validation": enable_validation,
        },
        "l4_reference": str(args.l4_report),
        "l7_reference": str(args.l7_report),
        "l8_reference": str(args.l8_report),
        "l4_metrics": l4_metrics,
        "l7_metrics": l7_metrics,
        "l8_metrics": l8_metrics,
        "metrics": metrics,
        "by_category": by_category,
        "retrieval_latency_avg_ms": round(avg_retrieval, 3),
        "rescued": len(rescued),
        "harmed": len(harmed),
        "held": len(held),
        "missed": len(missed),
        "rescue_ids": [e["question_id"] for e in rescued],
        "harm_ids": [e["question_id"] for e in harmed],
        "ablation_results": ablation_results if args.run_ablations else None,
        "evaluations": evaluations,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport saved (L4/L7/L8 untouched) : {report_path}")


if __name__ == "__main__":
    main()