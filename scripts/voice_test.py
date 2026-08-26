
"""One-shot voice test: fresh recordings + full pipeline, in one command.

    python scripts/voice_test.py                     # wipe old audio, record all, run everything
    python scripts/voice_test.py --keep-audio        # keep previous recordings (A/B comparisons)
    python scripts/voice_test.py --mic 1             # pick the microphone (see --list-devices)
    python scripts/voice_test.py --no-phonetic       # L6 ablation switch
    python scripts/voice_test.py --llm-model qwen2.5-coder:3b

Every run starts from a clean audio folder by default: previous recordings
are deleted, so all manifest questions are re-recorded from scratch. The
pipeline then runs automatically: Whisper -> L6 phonetic normalization ->
Ollama SQL -> execution.
"""

import argparse
import importlib.util
import os
import sys
import tempfile
import wave
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.record_audio import DEFAULT_MANIFEST, DEFAULT_QUESTIONS
from scripts.l5_asr import (
    DEFAULT_DB, DEFAULT_MODEL, DEFAULT_REPORT, WhisperEngine, probe_ollama,
)

AUDIO_DIR = PROJECT_ROOT / "backend" / "datasets" / "custom" / "spoken" / "audio"


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_silence_wav(target, seconds=0.5, rate=16000):
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return target


def effective_backend(args):
    if args.backend == "faster-whisper":
        return "faster-whisper"
    if args.backend == "whisper":
        return "openai-whisper"
    try:
        import faster_whisper  # noqa: PLC0415
        return "faster-whisper"
    except ImportError:
        return "openai-whisper"


def download_whisper_model(name, backend):
    if backend == "openai-whisper":
        import whisper
        whisper.load_model(name)  # -> ~/.cache/whisper/<name>.pt
    else:
        from huggingface_hub import snapshot_download
        snapshot_download(
            f"Systran/faster-whisper-{name}",
            cache_dir=str(Path.home() / ".cache" / "huggingface" / "hub"),
        )


def ensure_whisper_model(args):
    """Verify the Whisper model is usable; download it once if missing."""
    probe = write_silence_wav(Path(tempfile.gettempdir()) / "voice_test_probe.wav")
    engine = WhisperEngine(
        model_name=args.asr_model,
        device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        backend=args.backend,
    )
    result = engine.transcribe(str(probe))
    if result.success:
        print(f"Whisper model '{args.asr_model}': OK")
        return
    backend = effective_backend(args)
    print(f"Whisper model '{args.asr_model}' is not available ({result.error}).")
    print(f"Downloading '{args.asr_model}' for backend {backend} (one-time, needs internet)...")
    try:
        download_whisper_model(args.asr_model, backend)
        print("Download finished - verifying...")
        result = engine.transcribe(str(probe))
        if result.success:
            print(f"Whisper model '{args.asr_model}': OK")
        else:
            print(f"ERROR: model still not usable: {result.error}", file=sys.stderr)
            sys.exit(1)
    except Exception as exc:
        print(f"ERROR: could not download the Whisper model: {exc}", file=sys.stderr)
        print("Check your internet connection and re-run, or set --asr-model.", file=sys.stderr)
        sys.exit(1)


def clear_audio_folder():
    if not AUDIO_DIR.exists():
        return
    removed = sorted(AUDIO_DIR.glob("*.wav"))
    for target in removed:
        target.unlink()
    if removed:
        print(f"Cleared {len(removed)} previous recording(s) - starting fresh.")


def main():
    parser = argparse.ArgumentParser(
        description="Record fresh audio and run the full L1-L6 pipeline"
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--asr-model", default="base", help="whisper model (downloaded on first use)")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8", help="faster-whisper compute type (int8 recommended on CPU)")
    parser.add_argument("--language", default=None)
    parser.add_argument("--backend", default="auto")
    parser.add_argument("--llm-model", default=DEFAULT_MODEL, help="Ollama model (e.g. qwen2.5-coder:3b)")
    parser.add_argument("--no-phonetic", action="store_true", help="disable L6 phonetic normalization (ablation)")
    parser.add_argument("--limit", type=int, default=None, help="only process first N samples")
    parser.add_argument("--mic", type=int, default=None, help="pyaudio microphone input device index (default: auto-detect the active microphone; see record_audio.py --list-devices)")
    parser.add_argument("--force", action="store_true", help="re-record even samples that have audio (kept for compatibility)")
    parser.add_argument("--seconds", type=float, default=6.0, help="recording duration in seconds per question")
    parser.add_argument("--keep-audio", action="store_true", help="do NOT clear previous recordings (use for A/B comparisons)")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()

    print("== Voice test: full pipeline (L1-L6) ==")
    probe_ollama(args.llm_model)
    print(f"Ollama model '{args.llm_model}': OK")
    ensure_whisper_model(args)

    if not args.keep_audio:
        clear_audio_folder()

    record = load_script("record_audio")
    record.run_record(argparse.Namespace(
        manifest=args.manifest, questions=args.questions, limit=args.limit,
        device=args.mic, force=True, seconds=args.seconds,
    ))

    from scripts.l5_asr import run_manifest
    run_manifest(args)
    print("\nVoice test complete. Phonetic normalization:", "OFF" if args.no_phonetic else "ON")


if __name__ == "__main__":
    main()
