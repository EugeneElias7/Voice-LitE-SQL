"""Voice-LitE-SQL -- L6 experiment: database-aware phonetic normalization.

Offline measurement on corrupted_queries.json (20 ASR-noise pairs whose
targets are real schema terms). Reports per-pair results, three recovery
metrics, precision (drift on the clean originals), and an ablation of the
two components (phonetic encoding + multi-word merge).

Optional real-model experiment: ``--with-llm`` runs the corrupted / original
queries through the L3 LLM pipeline (with and without normalization) and
compares execution results. Requires Ollama; exits with a clear error when
unavailable (no mock substitution).

Usage:
    python scripts/l6_evaluator.py
    python scripts/l6_evaluator.py --with-llm --limit 10
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database.executor import execute_sql  # noqa: E402
from backend.evaluation.evaluator import results_equal  # noqa: E402
from backend.llm.ollama_client import DEFAULT_MODEL, OllamaError, generate  # noqa: E402
from backend.llm.sql_generator import generate_sql  # noqa: E402
from backend.phonetics import DatabaseAwareNormalizer, DatabaseVocabulary, NormalizerConfig  # noqa: E402

DEFAULT_SCHEMA = PROJECT_ROOT / "backend" / "datasets" / "custom" / "schema.json"
DEFAULT_CORRUPTED = PROJECT_ROOT / "backend" / "datasets" / "custom" / "corrupted_queries.json"
DEFAULT_DB = PROJECT_ROOT / "backend" / "data" / "enterprise.db"
RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"

def singular(token):
    return token[:-1] if token.endswith("s") and len(token) > 3 else token


def recovery_flags(pair, result):
    """(strict, equivalent, grounded) recovery of the target term."""
    corrected_strings = [c.corrected for c in result.corrections]
    schema_terms = [c.schema_term for c in result.corrections]
    text_tokens = set(result.text.split())
    target = pair["target"]

    strict = (
        target in text_tokens
        or target in corrected_strings
    )
    equivalent = strict or any(
        singular(c) == singular(target) or singular(s) == singular(target)
        for c in corrected_strings for s in (c,)
    ) or any(singular(s) == singular(target) for s in schema_terms)
    grounded = strict or any(s == target for s in schema_terms)
    return strict, equivalent, grounded


def evaluate_offline(normalizer, pairs):
    """Token-level metrics with documented classification.

    Per pair there is exactly one expected corrupted token (from the dev
    set ground truth). Classification over examined tokens:
      TP  - the expected token's correction (or the merge pass) recovers
            the target (singular-equivalent, or its parent column)
      FP  - any applied correction that does not recover a target
      FN  - expected token with no applied correction
      TN  - non-expected token left unchanged
    precision = TP/(TP+FP), recall = TP/(TP+FN),
    accuracy = (TP+TN)/tokens_examined.
    """
    per_pair = []
    examined = applied = tp = fp = fn = 0
    for pair in pairs:
        result = normalizer.correct(pair["corrupted"])
        strict, equivalent, grounded = recovery_flags(pair, result)
        expected = corrupted_token_of(pair)
        target = pair["target"]
        decisions = result.decisions
        expected_decisions = [
            d for d in decisions if expected is not None and d.original == expected
        ]
        applied_here = [d for d in decisions if d.applied]
        recovered = recovery_matches(normalizer.vocabulary, result, target)
        examined += len(decisions)
        applied += len(applied_here)
        if expected is not None:
            if recovered and any(d.applied for d in expected_decisions):
                tp += 1
            elif not recovered:
                fn += 1
        for d in applied_here:
            if not (expected is not None and d.original == expected and recovered):
                fp += 1
        per_pair.append(
            {
                "original": pair["original"],
                "corrupted": pair["corrupted"],
                "target": target,
                "expected_corrupted_token": expected,
                "corrected": result.text,
                "corrections": [c.__dict__ for c in result.corrections],
                "decisions": [d.__dict__ for d in decisions],
                "strict": strict,
                "equivalent": equivalent,
                "grounded": grounded,
            }
        )
    drift = []
    for pair in pairs:
        result = normalizer.correct(pair["original"])
        if result.corrections:
            drift.append(
                {
                    "original": pair["original"],
                    "corrected": result.text,
                    "corrections": [c.__dict__ for c in result.corrections],
                    "decisions": [d.__dict__ for d in result.decisions],
                }
            )

    tn = examined - applied - fn
    metrics = {
        "total_pairs": len(pairs),
        "strict_recovery": sum(p["strict"] for p in per_pair),
        "equivalent_recovery": sum(p["equivalent"] for p in per_pair),
        "grounded_recovery": sum(p["grounded"] for p in per_pair),
        "tokens_examined": examined,
        "corrections_applied": applied,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "unchanged_token_rate": round((examined - applied) / examined, 4) if examined else 0.0,
        "correction_precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
        "correction_recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        "correction_accuracy": round((tp + tn) / examined, 4) if examined else 0.0,
        "drift_texts": len(drift),
    }
    return {"metrics": metrics, "pairs": per_pair, "drift": drift}


def recovery_matches(vocabulary, result, target):
    """True when the correction records recover ``target``.

    A correction recovers the target when its replacement equals the
    target, is singular-equivalent to it, its parent column is the target,
    or (for merge records) the corrected text contains the target.
    """
    for correction in result.corrections:
        if correction.algorithm == "merge":
            if target in correction.corrected.split():
                return True
            continue
        replacement = correction.corrected
        if (
            replacement == target
            or singular(replacement) == singular(target)
            or correction.parent == target
            or correction.schema_term == target
        ):
            return True
    return False


def corrupted_token_of(pair):
    """The single token that differs between original and corrupted text.

    Returns None when the corruption is not a single-token substitution
    (e.g. 'higher' replacing 'hired' with extra words present).
    """
    original_words = clean_words(pair["original"])
    corrupted_words = clean_words(pair["corrupted"])
    if len(original_words) != len(corrupted_words):
        return None
    diffs = [
        c for o, c in zip(original_words, corrupted_words) if o != c
    ]
    return diffs[0] if len(diffs) == 1 else None


def clean_words(text):
    import re

    return [w for w in re.sub(r"[^a-z0-9 ]", " ", text.lower()).split()]


def print_offline(name, report):
    m = report["metrics"]
    print(f"\n{name}:")
    print(f"  strict recovery    : {m['strict_recovery']}/{m['total_pairs']}  ({m['strict_recovery'] / m['total_pairs']:.0%})")
    print(f"  equivalent recovery: {m['equivalent_recovery']}/{m['total_pairs']}  ({m['equivalent_recovery'] / m['total_pairs']:.0%})")
    print(f"  grounded recovery  : {m['grounded_recovery']}/{m['total_pairs']}  ({m['grounded_recovery'] / m['total_pairs']:.0%})")
    print(f"  tokens examined    : {m['tokens_examined']}")
    print(f"  corrections applied: {m['corrections_applied']}")
    print(f"  correction precision: {m['correction_precision']:.2%}")
    print(f"  correction recall  : {m['correction_recall']:.2%}")
    print(f"  correction accuracy: {m['correction_accuracy']:.2%}")
    print(f"  unchanged-token rate: {m['unchanged_token_rate']:.2%}")
    print(f"  drift on clean text: {m['drift_texts']}/{m['total_pairs']} texts")


def run_llm_ablation(pairs, db, model, limit):
    """A/B on the real LLM: corrupted vs original, with/without normalization.

    For each pair: execute SQL generated from (a) original, (b) corrupted,
    (c) normalized corrupted. Reports how often each condition matches the
    original answer.
    """
    probe = generate("Reply with exactly: OK", model=model, timeout=30)

    def answer_sql(text):
        result = generate_sql(text, db, model=model)
        if not result.success or not result.generated_sql:
            return None
        executed = execute_sql(result.generated_sql, db)
        if not executed.success:
            return None
        return executed

    original_rows, corrupted_rows, normalized_rows = [], [], []
    for pair in pairs[:limit]:
        original = answer_sql(pair["original"])
        corrupted = answer_sql(pair["corrupted"])
        normalized = answer_sql(normalizer.correct(pair["corrupted"]).text)
        original_rows.append((pair, original, corrupted, normalized))

    recovered_corrupted = 0
    recovered_normalized = 0
    details = []
    for pair, original, corrupted, normalized in original_rows:
        if original is None:
            continue
        ok_corrupted = corrupted is not None and results_equal(
            None, original, None, corrupted
        )
        ok_normalized = normalized is not None and results_equal(
            None, original, None, normalized
        )
        recovered_corrupted += ok_corrupted
        recovered_normalized += ok_normalized
        details.append(
            {
                "target": pair["target"],
                "corrupted": pair["corrupted"],
                "answer_recovered_from_corrupted": ok_corrupted,
                "answer_recovered_after_normalization": ok_normalized,
            }
        )
    return {
        "pairs_compared": len(original_rows),
        "answer_recovery_from_corrupted": recovered_corrupted,
        "answer_recovery_after_normalization": recovered_normalized,
        "details": details,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="L6 phonetic normalization experiment")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database (vocabulary via L2 Schema Inspector)")
    parser.add_argument("--schema", default=None, help="schema.json override (otherwise vocabulary comes from --db)")
    parser.add_argument("--corrupted", default=str(DEFAULT_CORRUPTED))
    parser.add_argument("--report", default=str(RESULTS_DIR / "l6_report.json"))
    parser.add_argument("--with-llm", action="store_true", help="run the real-model A/B experiment")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None, help="only first N pairs")
    args = parser.parse_args()

    with open(args.corrupted, encoding="utf-8") as handle:
        pairs = json.load(handle)
    if args.limit:
        pairs = pairs[:args.limit]

    if args.schema:
        vocabulary = DatabaseVocabulary.from_schema_json(args.schema)
    else:
        vocabulary = DatabaseVocabulary.from_database(args.db)
    normalizer = DatabaseAwareNormalizer(vocabulary)
    report = evaluate_offline(normalizer, pairs)
    print_offline("FULL (default config)", report)

    ablated_configs = [
        ("without phonetic encoding", NormalizerConfig(phonetic_min_score=99.0)),
        ("without multi-word merge", NormalizerConfig(merge_multiword=False)),
    ]
    ablations = {}
    for name, config in ablated_configs:
        ablated = evaluate_offline(DatabaseAwareNormalizer(vocabulary, config), pairs)
        ablations[name] = ablated["metrics"]
        print_offline(name, ablated)

    llm = None
    if args.with_llm:
        print("\n" + "=" * 60)
        print("REAL-MODEL A/B EXPERIMENT (Ollama)")
        print("=" * 60)
        print(f"Model     : {args.model}")
        print(f"Database  : {args.db}")
        try:
            llm = run_llm_ablation(pairs, args.db, args.model, args.limit)
        except OllamaError as exc:
            print(f"ERROR: Ollama is not available - {exc}", file=sys.stderr)
            print("Start Ollama (and make sure the model is pulled) then re-run.", file=sys.stderr)
            sys.exit(1)
        m = llm
        print(f"Pairs compared                    : {m['pairs_compared']}")
        print(f"Answer recovered from corrupted   : {m['answer_recovery_from_corrupted']}")
        print(f"Answer recovered after normalization: {m['answer_recovery_after_normalization']}")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "config": normalizer.config.__dict__,
        "vocabulary_source": "schema_inspector" if not args.schema else f"schema_json:{args.schema}",
        "database": str(args.db),
        "corrupted_queries_file": str(args.corrupted),
        "metrics": report["metrics"],
        "ablations": ablations,
        "llm_ablation": llm,
        "pairs": report["pairs"],
        "drift": report["drift"],
    }
    report_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"\nReport saved: {report_path}")
