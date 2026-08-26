"""Voice-LitE-SQL -- Level 5 tests: ASR engine, manifest, WER, pipeline.

Whisper is never invoked: the engine's ``_run_transcription`` seam is
mocked. No audio files, models, or network access are required.
"""

import json
import math
import struct
import wave
from pathlib import Path

import pytest

from backend.asr.models import (
    SpokenManifest,
    TranscriptionResult,
    compute_wer,
    load_manifest,
)
from backend.asr.whisper_engine import ASRError, WhisperEngine
from backend.database.executor import execute_sql
from backend.evaluation.evaluator import results_equal
from backend.llm import sql_generator
from backend.llm.sql_generator import generate_sql

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "backend" / "data" / "enterprise.db"
DATASET_DIR = PROJECT_ROOT / "backend" / "datasets" / "custom"
QUESTIONS_PATH = DATASET_DIR / "questions.json"
MANIFEST_PATH = DATASET_DIR / "spoken" / "manifest.json"


def make_wav(path, seconds=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        frames = b"".join(
            struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * t / 16000)))
            for t in range(int(16000 * seconds))
        )
        handle.writeframes(frames)
    return path


def mock_ready_engine(transcript="how many employees are there", language="en", duration=2.5):
    engine = WhisperEngine()

    def fake_import_backend():
        return "openai-whisper", None

    def fake_load_model(backend, module):
        return object()

    def fake_transcribe(backend, model, path):
        return transcript, language, duration

    engine._import_backend = fake_import_backend
    engine._model_available = lambda backend: True
    engine._load_model = fake_load_model
    engine._run_transcription = fake_transcribe
    return engine


def question(question_id):
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    return next(q for q in questions if q["id"] == question_id)


# -- audio validation --------------------------------------------------------

def test_missing_audio_file(tmp_path):
    engine = WhisperEngine()
    result = engine.transcribe(tmp_path / "nope.wav")
    assert not result.success
    assert "not found" in result.error
    assert result.transcript == ""


def test_audio_is_directory(tmp_path):
    engine = WhisperEngine()
    result = engine.transcribe(tmp_path)
    assert not result.success
    assert "not a file" in result.error


def test_empty_audio_file(tmp_path):
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")
    result = WhisperEngine().transcribe(empty)
    assert not result.success
    assert "empty" in result.error


def test_unsupported_audio_format(tmp_path):
    weird = tmp_path / "audio.txt"
    weird.write_text("not audio", encoding="utf-8")
    result = WhisperEngine().transcribe(weird)
    assert not result.success
    assert "unsupported audio format" in result.error


# -- configuration -----------------------------------------------------------

def test_engine_config_defaults():
    engine = WhisperEngine()
    assert engine.model_name == "small"
    assert engine.device == "cpu"
    assert engine.compute_type is None
    assert engine.language is None
    assert engine.backend == "auto"


def test_engine_config_custom():
    engine = WhisperEngine(
        model_name="small",
        device="cuda",
        compute_type="int8",
        language="en",
        backend="faster-whisper",
        download_root="C:/models",
    )
    assert engine.model_name == "small"
    assert engine.device == "cuda"
    assert engine.compute_type == "int8"
    assert engine.language == "en"
    assert engine.backend == "faster-whisper"
    assert engine.download_root == "C:/models"


# -- transcription results ---------------------------------------------------

def test_mocked_transcription_success(tmp_path):
    wav = make_wav(tmp_path / "q41.wav")
    engine = mock_ready_engine()
    result = engine.transcribe(wav)
    assert result.success
    assert result.transcript == "how many employees are there"
    assert result.language == "en"
    assert result.duration == 2.5
    assert result.transcription_time_ms >= 0
    assert result.error is None
    assert result.audio_path.endswith("q41.wav")


def test_transcription_result_to_dict():
    result = TranscriptionResult("a.wav", "hi", "base", language="en", success=True)
    data = result.to_dict()
    assert data["audio_path"] == "a.wav"
    assert data["transcript"] == "hi"
    assert data["model_name"] == "base"
    assert data["success"] is True
    assert data["error"] is None


def test_transcription_failure_controlled(tmp_path):
    wav = make_wav(tmp_path / "x.wav")
    engine = mock_ready_engine()

    def boom(backend, model, path):
        raise RuntimeError("decoder crashed")

    engine._run_transcription = boom
    result = engine.transcribe(wav)
    assert not result.success
    assert "transcription failed" in result.error


def test_missing_model_clear_error(tmp_path):
    wav = make_wav(tmp_path / "x.wav")
    engine = mock_ready_engine()

    def no_model(backend, module):
        raise ASRError(
            "whisper model 'base' not found locally. "
            "Download it manually first (it will not be downloaded automatically)."
        )

    engine._load_model = no_model
    result = engine.transcribe(wav)
    assert not result.success
    assert "model" in result.error.lower()
    assert "not found locally" in result.error


def test_missing_dependency_clear_error(tmp_path):
    wav = make_wav(tmp_path / "x.wav")
    engine = WhisperEngine(backend="faster-whisper")

    def no_module():
        raise ASRError("faster-whisper is not installed (pip install faster-whisper)")

    engine._import_backend = no_module
    result = engine.transcribe(wav)
    assert not result.success
    assert "faster-whisper" in result.error


def test_deterministic_mock_behavior(tmp_path):
    wav = make_wav(tmp_path / "x.wav")
    engine = mock_ready_engine(transcript="show total sales revenue")
    first = engine.transcribe(wav)
    second = engine.transcribe(wav)
    assert first.transcript == second.transcript == "show total sales revenue"
    assert first.language == second.language
    assert first.success == second.success


# -- WER ---------------------------------------------------------------------

def test_wer_perfect_and_noisy():
    assert compute_wer("how many employees are there", "how many employees are there") == 0.0
    assert compute_wer("show total sales revenue", "show total sails revenue") == pytest.approx(1 / 4)
    assert compute_wer("show total sales revenue", "show total") == pytest.approx(2 / 4)


def test_wer_edge_cases():
    assert compute_wer("", "") == 0.0
    assert compute_wer("", "something") == 1.0
    assert compute_wer("something", "") == 1.0


# -- manifest ----------------------------------------------------------------

def test_manifest_load_and_validate():
    manifest = load_manifest(MANIFEST_PATH, questions_path=QUESTIONS_PATH)
    assert isinstance(manifest, SpokenManifest)
    assert len(manifest.samples) >= 1
    sample = manifest.samples[0]
    assert sample.question_id
    assert sample.reference_text
    assert sample.audio_path
    assert manifest.audio_file(sample).name.endswith(".wav")


def test_manifest_invalid_question_id(tmp_path):
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps({"samples": [{"question_id": "q999", "reference_text": "x", "audio_path": "a/q999.wav"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown question_id"):
        load_manifest(manifest, questions_path=QUESTIONS_PATH)


def test_manifest_missing_fields(tmp_path):
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps({"samples": [{"question_id": "q01", "reference_text": "x"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing fields"):
        load_manifest(manifest, questions_path=QUESTIONS_PATH)


def test_manifest_unsafe_audio_path_rejected(tmp_path):
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps({"samples": [{"question_id": "q01", "reference_text": "x", "audio_path": "../evil.wav"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="relative"):
        load_manifest(manifest, questions_path=QUESTIONS_PATH)


# -- downstream pipeline (mocked ASR + mocked LLM, real executor) ------------

def test_downstream_pipeline_mocked_asr(tmp_path, monkeypatch):
    wav = make_wav(tmp_path / "q41.wav")
    engine = mock_ready_engine(transcript="How many employees are there?")
    transcription = engine.transcribe(wav)
    assert transcription.success

    q41 = question("q41")
    monkeypatch.setattr(
        sql_generator, "generate",
        lambda prompt, model=None, host=None, timeout=None: (q41["sql"], {}),
    )
    generated = generate_sql(transcription.transcript, DB_PATH)
    assert generated.success

    reference = execute_sql(q41["sql"], DB_PATH)
    executed = execute_sql(generated.generated_sql, DB_PATH)
    assert executed.success
    assert results_equal(q41["sql"], reference, generated.generated_sql, executed)


# -- no cloud dependency -----------------------------------------------------

def test_no_cloud_api_dependency():
    for filename in ("whisper_engine.py", "models.py"):
        source = (PROJECT_ROOT / "backend" / "asr" / filename).read_text(encoding="utf-8").lower()
        assert "import requests" not in source
        assert "urllib" not in source
        assert "http://" not in source
        assert "https://" not in source
        assert "api.openai" not in source
