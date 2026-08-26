"""Voice-LitE-SQL -- L5 ASR evaluation: real Whisper -> L6 phonetic
normalization -> L3 -> L4 pipeline.

Modes:
  --audio FILE        transcribe one audio file (no LLM needed)
  --manifest          evaluate the spoken manifest: transcribe every sample
                      that has audio, run database-aware phonetic
                      normalization (L6, frozen config) and the real L3/L4
                      pipeline, and compare against the reference SQL (by
                      question_id). Use --no-phonetic to disable the L6
                      stage (ablation).

No transcription result is ever fabricated: audio files must exist.

Usage:
  python scripts/l5_asr.py --audio path/to/file.wav
  python scripts/l5_asr.py --manifest --limit 3
  python scripts/l5_asr.py --manifest --no-phonetic   (ablation)
  python scripts/record_audio.py        (first: record the WAV files)
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.asr.models import compute_wer, load_manifest  # noqa: E402
from backend.asr.whisper_engine import WhisperEngine  # noqa: E402
from backend.database.executor import execute_sql  # noqa: E402
from backend.evaluation.evaluator import results_equal  # noqa: E402
from backend.llm.ollama_client import DEFAULT_MODEL, OllamaError, generate  # noqa: E402
from backend.llm.sql_generator import generate_sql  # noqa: E402
from backend.phonetics import DatabaseAwareNormalizer, DatabaseVocabulary  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "backend" / "data" / "enterprise.db"
DEFAULT_MANIFEST = PROJECT_ROOT / "backend" / "datasets" / "custom" / "spoken" / "manifest.json"
DEFAULT_QUESTIONS = PROJECT_ROOT / "backend" / "datasets" / "custom" / "questions.json"
DEFAULT_REPORT = PROJECT_ROOT / "evaluation" / "results" / "l5_report.json"


def make_normalizer(no_phonetic, db_path):
    """L6 stage: frozen-config normalizer, vocabulary from the L2 Schema
    Inspector. Returns None when the ablation flag is set."""
    if no_phonetic:
        return None
    vocabulary = DatabaseVocabulary.from_database(db_path)
    return DatabaseAwareNormalizer(vocabulary)


def probe_ollama(model):
    try:
        generate("Reply with exactly: OK", model=model, timeout=30)
    except OllamaError as exc:
        print(f"ERROR: Ollama is not available - {exc}", file=sys.stderr)
        print("Start Ollama (and make sure the model is pulled) then re-run.", file=sys.stderr)
        sys.exit(1)


def transcribe_single(audio, args):
    engine = WhisperEngine(
        model_name=args.asr_model,
        device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        backend=args.backend,
    )
    result = engine.transcribe(audio)
    print(json.dumps(result.to_dict(), indent=2))


def run_manifest(args):
    probe_ollama(args.llm_model)
    manifest = load_manifest(args.manifest, questions_path=args.questions)
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    by_id = {q["id"]: q for q in questions}

    normalizer = make_normalizer(args.no_phonetic, args.db)

    engine = WhisperEngine(
        model_name=args.asr_model,
        device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        backend=args.backend,
    )

    samples = manifest.samples[:args.limit] if args.limit else manifest.samples
    print(f"Manifest samples        : {len(manifest.samples)}")
    print(f"Will process            : {len(samples)}")
    print(f"Phonetic normalization  : {'ON (frozen L6 config)' if normalizer else 'OFF (ablation)'}")

    rows = []
    for sample in samples:
        audio = manifest.audio_file(sample)
        row = {
            "question_id": sample.question_id,
            "reference_text": sample.reference_text,
            "audio_exists": audio.exists(),
            "transcription_success": False,
            "transcript": None,
            "normalized_transcript": None,
            "corrections": [],
            "decisions": [],
            "wer": None,
            "transcription_time_ms": None,
            "generation_success": False,
            "execution_success": False,
            "correctness": False,
            "generated_sql": None,
            "error": None,
        }
        if not audio.exists():
            row["error"] = f"audio missing: {audio}"
            rows.append(row)
            continue
        transcription = engine.transcribe(audio)
        row["transcription_success"] = transcription.success
        row["transcription_time_ms"] = transcription.transcription_time_ms
        if not transcription.success:
            row["error"] = transcription.error
            rows.append(row)
            continue
        row["transcript"] = transcription.transcript
        row["wer"] = round(compute_wer(sample.reference_text, transcription.transcript), 4)
        question_text = transcription.transcript
        if normalizer is not None:
            normalized = normalizer.correct(transcription.transcript)
            row["normalized_transcript"] = normalized.text
            row["corrections"] = [c.__dict__ for c in normalized.corrections]
            row["decisions"] = [d.__dict__ for d in normalized.decisions]
            question_text = normalized.text
        question = by_id.get(sample.question_id)
        if question is None:
            row["error"] = f"question_id '{sample.question_id}' not in questions.json"
            rows.append(row)
            continue
        generated = generate_sql(question_text, args.db, model=args.llm_model)
        row["generation_success"] = generated.success
        if not generated.success:
            row["error"] = generated.error
            rows.append(row)
            continue
        row["generated_sql"] = generated.generated_sql
        reference = execute_sql(question["sql"], args.db)
        executed = execute_sql(generated.generated_sql, args.db)
        row["execution_success"] = executed.success
        if not executed.success:
            row["error"] = f"({executed.error_type}) {executed.error}"
            rows.append(row)
            continue
        row["correctness"] = results_equal(question["sql"], reference, generated.generated_sql, executed)
        rows.append(row)

    print_summary(rows)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "asr_model": args.asr_model,
        "llm_model": args.llm_model,
        "phonetic_normalization": normalizer is not None,
        "manifest": str(args.manifest),
        "rows": rows,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report saved            : {report_path}")


def print_summary(rows):
    total = len(rows)
    with_audio = sum(1 for r in rows if r["audio_exists"])
    transcribed = sum(1 for r in rows if r["transcription_success"])
    wer_values = [r["wer"] for r in rows if r["wer"] is not None]
    latencies = [r["transcription_time_ms"] for r in rows if r["transcription_time_ms"] is not None]
    generated = sum(1 for r in rows if r["generation_success"])
    executed = sum(1 for r in rows if r["execution_success"])
    correct = sum(1 for r in rows if r["correctness"])

    print("=" * 60)
    print("LEVEL 5 ASR EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Audio samples in manifest    : {total}")
    print(f"Samples with audio files     : {with_audio}")
    print(f"Successful transcriptions    : {transcribed}")
    if wer_values:
        print(f"Mean word error rate (WER)   : {sum(wer_values) / len(wer_values):.4f}")
    if latencies:
        print(f"Average transcription latency: {sum(latencies) / len(latencies):.1f} ms")
    print(f"Downstream SQL generation    : {generated}/{transcribed}")
    print(f"Downstream SQL execution     : {executed}/{transcribed}")
    print(f"Downstream execution accuracy: {correct}/{transcribed}")
    print()
    print(f"{'id':<6}{'audio':<7}{'transcribed':<12}{'WER':<8}{'gen':<5}{'exec':<5}{'acc':<5}")
    for row in rows:
        print(
            f"{row['question_id']:<6}{str(row['audio_exists']):<7}{str(row['transcription_success']):<12}"
            f"{(str(row['wer']) if row['wer'] is not None else '-'):<8}"
            f"{str(row['generation_success']):<5}{str(row['execution_success']):<5}{str(row['correctness']):<5}"
        )
        if row["corrections"]:
            print(f"       L6 corrections: {', '.join(f'{c['token']}->{c['corrected']}' for c in row['corrections'])}")
    if not with_audio:
        print()
        print("No audio files found. Record them first:")
        print("    python scripts/record_audio.py")
        print("Then re-run this script. Nothing was fabricated.")


def main():
    parser = argparse.ArgumentParser(description="L5 ASR evaluation (local Whisper)")
    parser.add_argument("--audio", help="transcribe a single audio file")
    parser.add_argument("--manifest", nargs="?", const=str(DEFAULT_MANIFEST), default=str(DEFAULT_MANIFEST), help="spoken manifest path")
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS), help="questions.json path")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="database path")
    parser.add_argument("--asr-model", default="small", help="whisper model name (must exist locally)")
    parser.add_argument("--device", default="cpu", help="cpu or cuda")
    parser.add_argument("--compute-type", default=None, help="faster-whisper compute type (int8, float16, ...)")
    parser.add_argument("--language", default=None, help="force transcription language (e.g. en)")
    parser.add_argument("--backend", default="auto", help="auto | whisper | faster-whisper")
    parser.add_argument("--llm-model", default=DEFAULT_MODEL, help="Ollama model for downstream SQL")
    parser.add_argument("--no-phonetic", action="store_true", help="disable L6 phonetic normalization (ablation)")
    parser.add_argument("--limit", type=int, default=None, help="only process first N manifest samples")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="JSON report path")
    args = parser.parse_args()

    if args.audio:
        transcribe_single(args.audio, args)
    else:
        run_manifest(args)


if __name__ == "__main__":
    main()
