"""Voice-LitE-SQL -- L3 live simulator: run the REAL Ollama model on questions.

The model answers are genuine qwen2.5-coder:1.5b generations, not mocks.

Modes:
  interactive                   type questions, see the model answer (Ctrl+C to exit)
  --question "<text>"           one custom question
  --questions <file.json>       batch through questions.json (or any Q-SQL file)
  --limit N                     only run the first N questions in batch mode

Usage:
  python scripts/l3_simulator.py
  python scripts/l3_simulator.py --question "How many employees are there?"
  python scripts/l3_simulator.py --questions backend/datasets/custom/questions.json
  python scripts/l3_simulator.py --questions backend/datasets/custom/questions.json --limit 5
"""

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.llm.sql_generator import generate_sql  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "backend" / "data" / "enterprise.db"


def run_question(question, db_path, label=""):
    prefix = f"[{label}] " if label else ""
    print(f"{prefix}QUESTION : {question}")
    started = time.monotonic()
    result = generate_sql(question, db_path)
    elapsed = time.monotonic() - started
    print(f"{prefix}MODEL    : {result.model_name}")
    if result.success:
        print(f"{prefix}SQL      : {result.generated_sql}")
        print(f"{prefix}STATUS   : GENERATED OK")
    else:
        print(f"{prefix}SQL      : (none)")
        print(f"{prefix}STATUS   : FAILED - {result.error}")
    print(f"{prefix}TIME     : {elapsed:.1f}s")
    print(f"{prefix}RAW      : {result.raw_response[:200].strip()}")
    print("-" * 70)
    return result


def run_batch(path, db_path, limit=None):
    path = Path(path)
    with open(path, encoding="utf-8") as handle:
        questions = json.load(handle)
    if limit:
        questions = questions[:limit]
    total = len(questions)
    generated = 0
    print(f"Running {total} questions through the REAL model ({path.name}).\n")
    for index, item in enumerate(questions, start=1):
        result = run_question(item["question"], db_path, label=f"{index}/{total} {item.get('id', '')}")
        expected = item.get("sql", "").strip()
        if result.success:
            generated += 1
            match = "EXACT MATCH" if result.generated_sql == expected else "DIFFERS"
            print(f"  EXPECTED : {expected}")
            print(f"  MATCH    : {match}")
            print("-" * 70)
    print(f"\nSummary: {generated}/{total} generated successfully.")
    if generated < total:
        print(f"  {total - generated} question(s) failed generation (see FAILED rows above).")
    print("  NOTE: string match only. Semantic/execution correctness comes in L4.")


def interactive(db_path):
    print("Voice-LitE-SQL L3 simulator (real Ollama model).")
    print("Type a question and press Enter. Ctrl+C or 'quit' to exit.\n")
    try:
        while True:
            question = input("You: ").strip()
            if not question or question.lower() in ("quit", "exit"):
                break
            run_question(question, db_path)
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")


def main():
    parser = argparse.ArgumentParser(description="L3 live simulator (real Ollama model)")
    parser.add_argument("--question", help="run a single custom question")
    parser.add_argument("--questions", help="batch-run a questions.json file")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="database path")
    parser.add_argument("--limit", type=int, default=None, help="batch: only first N questions")
    args = parser.parse_args()

    if args.question:
        run_question(args.question, args.db)
    elif args.questions:
        run_batch(args.questions, args.db, limit=args.limit)
    else:
        interactive(args.db)


if __name__ == "__main__":
    main()
