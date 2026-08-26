"""Voice-LitE-SQL -- L4 baseline experiment: real Ollama model -> SQL -> execute.

Runs the L3 baseline (qwen2.5-coder:1.5b) on questions.json, executes the
generated and reference SQL against enterprise.db, compares normalized
results, prints metrics, and saves a JSON report.

Usage:
    python scripts/l4_evaluator.py
    python scripts/l4_evaluator.py --limit 10 --model qwen2.5-coder:1.5b

Exits with a clear error if Ollama is unavailable (no mock substitution).
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

from backend.evaluation.evaluator import run_evaluation  # noqa: E402
from backend.evaluation.metrics import compute_metrics, metrics_by_category  # noqa: E402
from backend.llm.ollama_client import DEFAULT_MODEL, OllamaError, generate  # noqa: E402
from backend.llm.sql_generator import generate_sql  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "backend" / "data" / "enterprise.db"
DEFAULT_QUESTIONS = PROJECT_ROOT / "backend" / "datasets" / "custom" / "questions.json"
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"

CATEGORY_ORDER = ["SELECT", "WHERE", "JOIN", "GROUP BY", "ORDER BY", "aggregate", "complex"]


def db_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probe_ollama(model):
    try:
        generate("Reply with exactly: OK", model=model, timeout=30)
    except OllamaError as exc:
        print(f"ERROR: Ollama is not available - {exc}", file=sys.stderr)
        print("Start Ollama (and make sure the model is pulled) then re-run.", file=sys.stderr)
        sys.exit(1)


def print_summary(metrics):
    print("=" * 60)
    print("LEVEL 4 BASELINE SUMMARY")
    print("=" * 60)
    print(f"Total questions            : {metrics['total_questions']}")
    print(f"Generation success rate    : {metrics['generation_success_rate'] * 100:.1f}%")
    print(f"Execution success rate     : {metrics['execution_success_rate'] * 100:.1f}%")
    print(f"Execution accuracy         : {metrics['execution_accuracy'] * 100:.1f}%")
    print(f"SQL execution error rate   : {metrics['sql_execution_error_rate'] * 100:.1f}%")
    print(f"Average execution latency  : {metrics['average_execution_latency_ms']} ms")
    print(f"Median execution latency   : {metrics['median_execution_latency_ms']} ms")


def print_category_table(by_category):
    print()
    print("=" * 60)
    print("CATEGORY-LEVEL METRICS")
    print("=" * 60)
    print(f"{'Category':<12}{'N':>4}{'Gen%':>8}{'Exec%':>8}{'Acc%':>8}")
    for category in CATEGORY_ORDER:
        metrics = by_category.get(category)
        if not metrics:
            continue
        print(
            f"{category:<12}{metrics['total_questions']:>4}"
            f"{metrics['generation_success_rate'] * 100:>7.1f}%"
            f"{metrics['execution_success_rate'] * 100:>7.1f}%"
            f"{metrics['execution_accuracy'] * 100:>7.1f}%"
        )


def print_examples(evaluations):
    correct = [e for e in evaluations if e.correctness]
    failed_execution = [e for e in evaluations if not e.execution_success and e.execution_error_type != "generation_error"]
    incorrect = [e for e in evaluations if e.generation_success and e.execution_success and not e.correctness]

    print()
    print("=" * 60)
    print("EXAMPLE SUCCESSFUL QUERIES")
    print("=" * 60)
    for e in correct[:3]:
        print(f"[{e.question_id} | {e.category}] {e.question}")
        print(f"  SQL: {e.generated_sql}")

    print()
    print("=" * 60)
    print("EXAMPLE EXECUTION FAILURES")
    print("=" * 60)
    for e in failed_execution[:3]:
        print(f"[{e.question_id} | {e.category}] {e.question}")
        print(f"  SQL   : {e.generated_sql}")
        print(f"  ERROR : ({e.execution_error_type}) {e.execution_error}")

    print()
    print("=" * 60)
    print("EXAMPLE INCORRECT-BUT-EXECUTABLE SQL")
    print("=" * 60)
    for e in incorrect[:3]:
        print(f"[{e.question_id} | {e.category}] {e.question}")
        print(f"  GENERATED : {e.generated_sql}")
        print(f"  REFERENCE : {e.reference_sql}")


def main():
    parser = argparse.ArgumentParser(description="L4 baseline experiment (real Ollama model)")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="database path")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS), help="questions.json path")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model name")
    parser.add_argument("--limit", type=int, default=None, help="only first N questions")
    parser.add_argument("--report", default=str(RESULTS_DIR / "l4_report.json"), help="JSON report path")
    args = parser.parse_args()

    print("=" * 60)
    print("LEVEL 4 BASELINE EVALUATION (real Ollama model)")
    print("=" * 60)
    print(f"Model     : {args.model}")
    print(f"Database  : {args.db}")
    print(f"Questions : {args.questions}")

    probe_ollama(args.model)

    with open(args.questions, encoding="utf-8") as handle:
        questions = json.load(handle)
    if args.limit:
        questions = questions[:args.limit]
    print(f"Running   : {len(questions)} questions")

    sha_before = db_sha256(args.db)
    evaluations = run_evaluation(
        questions,
        lambda q: generate_sql(q, args.db, model=args.model),
        args.db,
    )
    sha_after = db_sha256(args.db)
    database_intact = sha_before == sha_after

    metrics = compute_metrics(evaluations)
    by_category = metrics_by_category(evaluations)

    print_summary(metrics)
    print_category_table(by_category)
    print_examples(evaluations)
    print()
    print(f"Database integrity        : {'INTACT (sha256 unchanged)' if database_intact else 'CHANGED!'}")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "database": str(args.db),
        "questions_file": str(args.questions),
        "database_intact": database_intact,
        "metrics": metrics,
        "by_category": by_category,
        "evaluations": [e.to_dict() for e in evaluations],
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report saved              : {report_path}")


if __name__ == "__main__":
    main()
