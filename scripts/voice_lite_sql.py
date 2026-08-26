#!/usr/bin/env python3
"""Voice-LitE-SQL -- Level 9: Interactive CLI for the full voice-to-SQL pipeline.

Usage:
    python scripts/voice_lite_sql.py                    # Interactive mode (speak)
    python scripts/voice_lite_sql.py --text "question"  # Text debug mode
    python scripts/voice_lite_sql.py --audio file.wav   # Audio file mode
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.pipeline import VoiceLitESQLPipeline, PipelineConfig
from backend.pipeline.pipeline_result import PipelineResult


DEFAULT_DB = PROJECT_ROOT / "backend" / "data" / "enterprise.db"
DEFAULT_QUESTIONS = PROJECT_ROOT / "backend" / "datasets" / "custom" / "questions.json"
DEFAULT_MANIFEST = PROJECT_ROOT / "backend" / "datasets" / "custom" / "spoken" / "manifest.json"


def print_banner():
    print("=" * 60)
    print("   Voice-LitE-SQL")
    print("   Local Voice -> SQL Assistant")
    print("=" * 60)
    print()


def print_stage_info(stage_name: str, stage_data, indent: int = 2):
    """Pretty print stage information."""
    prefix = " " * indent
    print(f"{prefix}{stage_name}:")
    if hasattr(stage_data, '__dict__'):
        for key, value in stage_data.__dict__.items():
            if key.startswith('_'):
                continue
            if isinstance(value, (list, dict)) and value:
                print(f"{prefix}  {key}: {json.dumps(value, default=str)[:200]}")
            elif value not in (None, "", [], {}):
                print(f"{prefix}  {key}: {value}")
    print()


def run_interactive_mode(pipeline: VoiceLitESQLPipeline):
    """Interactive voice mode - placeholder for microphone capture."""
    print("Interactive mode requires microphone capture.")
    print("Use: python scripts/record_audio.py to record WAV files first.")
    print("Then use: python scripts/voice_lite_sql.py --audio path/to/file.wav")
    return


def run_text_mode(pipeline: VoiceLitESQLPipeline, question: str, question_id: str = None):
    """Run a single text query through the pipeline."""
    # Try to find reference SQL from questions.json by exact question match
    reference_sql = None
    with open(DEFAULT_QUESTIONS, encoding="utf-8") as f:
        questions = json.load(f)
    for q in questions:
        if q.get("question") == question:
            reference_sql = q.get("sql")
            question_id = q.get("id")
            break

    print(f"\nQuestion: {question}")
    print("-" * 60)

    result = pipeline.run_text_query(question, question_id=question_id, reference_sql=reference_sql)

    # Print concise stage information
    if result.normalization:
        print(f"Normalized: {result.normalization.normalized_text}")

    if result.nlp:
        intent = result.nlp.intent.get('primary_intent', 'UNKNOWN')
        join_req = result.nlp.intent.get('join_required', False)
        print(f"Intent: {intent} (join_required={join_req})")

        if result.nlp.linked_entities:
            tables = set(e['table'] for e in result.nlp.linked_entities if e.get('table'))
            columns = [f"{e['table']}.{e['column']}" for e in result.nlp.linked_entities if e.get('table') and e.get('column')]
            if tables:
                print(f"Tables: {', '.join(sorted(tables))}")
            if columns:
                print(f"Columns: {', '.join(columns[:5])}")

        if result.nlp.relationship_decisions:
            rels = [f"{r['source_table']}.{r['source_column']}->{r['target_table']}.{r['target_column']} ({'REQUIRED' if r['required'] else 'filtered'})"
                    for r in result.nlp.relationship_decisions]
            for r in rels[:3]:
                print(f"  Relationship: {r}")

    if result.retrieval:
        print(f"Retrieved: {len(result.retrieval.retrieved_items)} schema items")

    if result.generation:
        print(f"Generated SQL:")
        print(f"  {result.generation.generated_sql}")

    if result.validation:
        status = "PASS" if result.validation.is_valid else "FAIL"
        print(f"Validation: {status}")
        if not result.validation.is_valid:
            for issue in result.validation.issues[:3]:
                print(f"  - {issue['code']}: {issue['message']}")

    if result.execution:
        status = "SUCCESS" if result.execution.success else "ERROR"
        print(f"Execution: {status}")
        if result.execution.error:
            print(f"  Error: {result.execution.error}")
        elif result.execution.rows:
            print(f"  Rows: {len(result.execution.rows)}")
            if result.execution.columns:
                print(f"  Columns: {', '.join(result.execution.columns)}")
                for row in result.execution.rows[:3]:
                    print(f"    {row}")

    if result.correction and result.correction.attempts:
        print(f"Correction: {result.correction.total_attempts} attempts")
        for attempt in result.correction.attempts:
            print(f"  Attempt {attempt['attempt_number']}: {'CORRECT' if attempt['is_correct'] else 'INCORRECT'}")

    if result.final_sql:
        print(f"\nFinal SQL:")
        print(f"  {result.final_sql}")

    if result.final_correct:
        print(f"\nAnswer: CORRECT")
    elif result.final_status == "success":
        print(f"\nAnswer: EXECUTED (correctness unknown)")
    else:
        print(f"\nAnswer: FAILED")

    print(f"Total latency: {result.total_latency_ms:.0f}ms")
    if result.stage_latencies:
        print("Latency breakdown:")
        for stage, latency in sorted(result.stage_latencies.items(), key=lambda x: -x[1]):
            print(f"  {stage}: {latency:.0f}ms")

    return result


def run_audio_mode(pipeline: VoiceLitESQLPipeline, audio_path: str, reference_transcript: str = None):
    """Run an audio file through the pipeline."""
    print(f"\nAudio: {audio_path}")
    print("-" * 60)

    result = pipeline.run_voice_query(
        audio_path,
        reference_transcript=reference_transcript
    )

    if result.asr:
        print(f"Transcript: {result.asr.raw_transcript}")
        if result.asr.wer is not None:
            print(f"WER: {result.asr.wer:.3f}")

    if result.normalization:
        print(f"Normalized: {result.normalization.normalized_text}")

    # Reuse text mode display for remaining stages
    text_result = type('obj', (object,), {
        'nlp': result.nlp,
        'retrieval': result.retrieval,
        'generation': result.generation,
        'validation': result.validation,
        'execution': result.execution,
        'correction': result.correction,
        'final_sql': result.final_sql,
        'final_correct': result.final_correct,
        'final_status': result.final_status,
        'stage_latencies': result.stage_latencies,
        'total_latency_ms': result.total_latency_ms,
    })
    run_text_mode.__globals__['_display_result'] = lambda r: None
    return result


def run_evaluation_mode(pipeline: VoiceLitESQLPipeline, limit: int = None, offset: int = 0):
    """Run the controlled 50-question evaluation (optionally a slice)."""
    with open(DEFAULT_QUESTIONS, encoding="utf-8") as f:
        questions = json.load(f)

    if limit:
        questions = questions[offset:offset + limit]
    else:
        questions = questions[offset:]

    print(f"Running evaluation on {len(questions)} questions...")
    print("-" * 60)

    results = []
    correct = 0
    for q in questions:
        result = pipeline.run_text_query(
            q["question"],
            question_id=q["id"],
            category=q.get("category"),
            reference_sql=q.get("sql"),
        )
        results.append(result)
        if result.final_correct:
            correct += 1
        status = "OK" if result.final_correct else "FAIL"
        print(f"{status} [{q['id']}] {q['question'][:50]}...")

    accuracy = correct / len(results) * 100
    print(f"\nAccuracy: {correct}/{len(results)} = {accuracy:.1f}%")
    return results


def run_audio_evaluation_mode(pipeline: VoiceLitESQLPipeline, limit: int = None, offset: int = 0):
    """Run the 8 real-audio sample evaluation from the spoken manifest."""
    if not DEFAULT_MANIFEST.exists():
        print(f"ERROR: manifest not found: {DEFAULT_MANIFEST}")
        return []

    with open(DEFAULT_MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)

    samples = manifest["samples"]
    if limit:
        samples = samples[offset:offset + limit]
    else:
        samples = samples[offset:]

    with open(DEFAULT_QUESTIONS, encoding="utf-8") as f:
        questions = json.load(f)
    sql_by_id = {q["id"]: q.get("sql") for q in questions}
    category_by_id = {q["id"]: q.get("category") for q in questions}

    print(f"Running audio evaluation on {len(samples)} samples...")
    print("-" * 60)

    results = []
    for s in samples:
        audio_path = PROJECT_ROOT / "backend" / "datasets" / "custom" / "spoken" / s["audio_path"]
        qid = s["question_id"]
        result = pipeline.run_voice_query(
            str(audio_path),
            question_id=qid,
            category=category_by_id.get(qid),
            reference_sql=sql_by_id.get(qid),
            reference_transcript=s.get("reference_text"),
        )
        results.append(result)
        wer = result.asr.wer if result.asr else None
        wer_s = f"{wer * 100:.1f}%" if wer is not None else "n/a"
        status = "OK" if result.final_correct else "FAIL"
        print(f"{status} [{qid}] WER={wer_s} transcript={result.asr.raw_transcript if result.asr else ''!r}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Voice-LitE-SQL L9 Pipeline")
    parser.add_argument("--text", type=str, help="Run text query")
    parser.add_argument("--audio", type=str, help="Run audio file")
    parser.add_argument("--interactive", action="store_true", help="Interactive voice mode")
    parser.add_argument("--evaluate", action="store_true", help="Run 50-question evaluation")
    parser.add_argument("--evaluate-audio", action="store_true", help="Run 8-file audio evaluation")
    parser.add_argument("--limit", type=int, default=None, help="Limit evaluation questions")
    parser.add_argument("--offset", type=int, default=0, help="Start evaluation questions at this index")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB), help="Database path")
    parser.add_argument("--fake-embedder", action="store_true", help="Use fake embedder")
    parser.add_argument("--no-nlp", action="store_true", help="Disable L8.1 NLP")
    parser.add_argument("--no-correction", action="store_true", help="Disable L8 correction")
    parser.add_argument("--no-validation", action="store_true", help="Disable SQL validation")
    parser.add_argument("--report", type=str, help="Save results to JSON report")

    args = parser.parse_args()

    print_banner()
    print(f"Database: {args.db}")

    config = PipelineConfig(
        db_path=args.db,
        fake_embedder=args.fake_embedder,
        enable_nlp=not args.no_nlp,
        enable_correction=not args.no_correction,
        enable_validation=not args.no_validation,
    )
    pipeline = VoiceLitESQLPipeline(config)

    if args.evaluate:
        results = run_evaluation_mode(pipeline, args.limit, args.offset)
        if args.report:
            report = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "accuracy": sum(r.final_correct for r in results) / len(results),
                "total": len(results),
                "results": [r.to_dict() for r in results],
            }
            Path(args.report).write_text(json.dumps(report, indent=2))
            print(f"Report saved: {args.report}")
    elif args.evaluate_audio:
        results = run_audio_evaluation_mode(pipeline, args.limit, args.offset)
        if args.report:
            report = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "accuracy": sum(r.final_correct for r in results) / len(results) if results else 0.0,
                "total": len(results),
                "results": [r.to_dict() for r in results],
            }
            Path(args.report).write_text(json.dumps(report, indent=2))
            print(f"Report saved: {args.report}")
    elif args.text:
        run_text_mode(pipeline, args.text)
    elif args.audio:
        run_audio_mode(pipeline, args.audio)
    elif args.interactive:
        run_interactive_mode(pipeline)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()