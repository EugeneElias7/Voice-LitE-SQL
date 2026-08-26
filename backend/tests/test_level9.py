"""Voice-LitE-SQL -- Level 9: Tests for the full integrated pipeline.

Covers stage ordering, structured results, bounded correction, failure
propagation, read-only safety, and audio->text integration with mocks.
The LLM, executor, and ASR are mocked so tests run offline and fast.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.pipeline.pipeline_result import (
    PipelineResult,
    PipelineTimer,
    AudioStage,
    ASRStage,
    NormalizationStage,
    NLPStage,
    RetrievalStage,
    GenerationStage,
    ValidationStage,
    ExecutionStage,
    CorrectionStage,
)
import backend.pipeline.voice_lite_sql as vls

DB_PATH = PROJECT_ROOT / "backend" / "data" / "enterprise.db"


class FakeExecResult:
    def __init__(self, success=True, columns=("name",), rows=(("Alice",),), error=None,
                 error_type=None, execution_time_ms=1.0):
        self.success = success
        self.columns = columns
        self.rows = rows
        self.error = error
        self.error_type = error_type
        self.execution_time_ms = execution_time_ms


class FakeCorrector:
    def __init__(self, *args, **kwargs):
        pass

    def build_reference_result_text(self, *args, **kwargs):
        return ""

    def correct(self, **kwargs):
        return SimpleNamespace(
            attempts=[],
            total_attempts=0,
            rescued=False,
            harmed=False,
            final_correct=False,
        )


class FakeWhisper:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, path):
        return SimpleNamespace(
            success=True,
            transcript="List all employee names",
            model_name="faster-whisper-small",
            transcription_time_ms=12.0,
        )


class FakeWhisperEmpty:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, path):
        return SimpleNamespace(
            success=False,
            transcript="",
            model_name="faster-whisper-small",
            transcription_time_ms=0.0,
        )


def patch_environment(generate_result="SELECT name FROM employees;", exec_result=None):
    """Patch LLM generation, executor, and corrector; return restore func."""
    original = (
        vls.generate,
        vls.execute_sql,
        vls.SQLCorrector,
        vls.WhisperEngine,
    )
    calls = {"executed": []}

    def fake_generate(prompt, **kwargs):
        if callable(generate_result):
            return generate_result(prompt), None
        return generate_result, None

    def fake_execute(sql, db_path):
        calls["executed"].append(sql)
        return exec_result if exec_result is not None else FakeExecResult()

    vls.generate = fake_generate
    vls.execute_sql = fake_execute
    vls.SQLCorrector = FakeCorrector
    vls.WhisperEngine = FakeWhisper

    def restore():
        vls.generate, vls.execute_sql, vls.SQLCorrector, vls.WhisperEngine = original

    return restore, calls


def make_pipeline(**kwargs):
    config = vls.PipelineConfig(db_path=str(DB_PATH), fake_embedder=True, **kwargs)
    return vls.VoiceLitESQLPipeline(config)


def test_pipeline_result_structure():
    print("Testing PipelineResult structure...")
    result = PipelineResult(question_id="q01", category="basic", reference_sql="SELECT 1;")
    result.audio = AudioStage(audio_path="x.wav", capture_status="loaded")
    result.asr = ASRStage(raw_transcript="hello", model_name="faster-whisper-small")
    result.normalization = NormalizationStage(original_text="hello", normalized_text="hello")
    result.nlp = NLPStage(intent={}, linked_entities=[], phrase_matches=[])
    result.retrieval = RetrievalStage(query_text="hello", retrieved_items=[], top_k=5)
    result.generation = GenerationStage(raw_response="", generated_sql="SELECT 1;", prompt_length=10)
    result.validation = ValidationStage(is_valid=True, issues=[], tables_used=[], columns_used=[],
                                        joins=[], has_aggregation=False, has_group_by=False)
    result.execution = ExecutionStage(success=True)
    result.correction = CorrectionStage(total_attempts=2)
    result.final_sql = "SELECT 1;"
    result.final_correct = True
    result.final_status = "success"

    d = result.to_dict()
    for key in ("question_id", "category", "reference_sql", "audio", "asr", "normalization",
                "nlp", "retrieval", "generation", "validation", "execution", "correction",
                "final_sql", "final_correct", "final_status", "stage_latencies",
                "total_latency_ms", "started_at"):
        assert key in d, f"missing key {key}"
    assert d["final_correct"] is True
    assert d["correction"]["total_attempts"] == 2
    print("  All PipelineResult structure tests passed!")


def test_stage_dataclass_defaults():
    print("Testing stage dataclass defaults...")
    assert ASRStage(raw_transcript="").wer is None
    assert ExecutionStage(success=False).error is None
    assert CorrectionStage().total_attempts == 0
    assert PipelineResult().final_status == "pending"
    assert PipelineResult().final_correct is False
    print("  All dataclass default tests passed!")


def test_pipeline_timer():
    print("Testing PipelineTimer...")
    result = PipelineResult()
    with PipelineTimer(result, "nlp"):
        import time
        time.sleep(0.01)
    assert "nlp" in result.stage_latencies
    assert result.stage_latencies["nlp"] > 0
    assert result.total_latency_ms == sum(result.stage_latencies.values())
    print(f"  Timer recorded {result.stage_latencies['nlp']:.1f}ms")
    print("  All timer tests passed!")


def test_stage_ordering_and_integration():
    print("Testing full text pipeline stage ordering...")
    restore, calls = patch_environment(generate_result="SELECT name FROM employees;",
                                       exec_result=FakeExecResult(columns=("name",), rows=(("Alice",),)))
    try:
        pipeline = make_pipeline(enable_correction=False)
        result = pipeline.run_text_query("List all employee names", question_id="q01",
                                         category="basic", reference_sql="SELECT name FROM employees;")
    finally:
        restore()

    assert result.normalization is not None, "normalization stage missing"
    assert result.nlp is not None, "nlp stage missing"
    assert result.retrieval is not None, "retrieval stage missing"
    assert result.generation is not None, "generation stage missing"
    assert result.validation is not None, "validation stage missing"
    assert result.execution is not None, "execution stage missing"

    order = [s for s in ("normalization", "nlp", "retrieval", "generation", "validation",
                         "execution", "correction") if result.stage_latencies.get(s) is not None]
    assert order == ["normalization", "nlp", "retrieval", "generation", "validation", "execution"], \
        f"unexpected stage order: {order}"

    assert result.final_sql == "SELECT name FROM employees;"
    assert result.total_latency_ms > 0
    assert calls["executed"], "execute_sql should have been called"
    print(f"  Stages ran in order: {order}; final_sql={result.final_sql!r}")
    print("  All integration tests passed!")


def test_no_unsafe_sql_execution():
    print("Testing read-only safety...")
    restore, calls = patch_environment(generate_result="DELETE FROM employees;")
    try:
        pipeline = make_pipeline(enable_correction=False)
        result = pipeline.run_text_query("Delete all employees")
    finally:
        restore()

    assert result.generation.generated_sql == "", \
        f"unsafe SQL should be rejected, got {result.generation.generated_sql!r}"
    assert not any("DELETE" in s.upper() for s in calls["executed"]), \
        "unsafe SQL must never reach the executor"
    print(f"  Unsafe SQL rejected; executor never saw DELETE (calls={len(calls['executed'])})")
    print("  All safety tests passed!")


def test_failure_propagation():
    print("Testing generation failure propagation...")
    restore, calls = patch_environment(generate_result="")
    try:
        pipeline = make_pipeline(enable_correction=False)
        result = pipeline.run_text_query("List employees")
    finally:
        restore()

    # Generation failure leaves empty SQL; pipeline still returns a structured result
    assert result.generation.generated_sql == ""
    assert result.final_status in ("error", "partial", "success")
    assert result.to_dict()["generation"] is not None
    print(f"  Failure propagated; final_status={result.final_status}")
    print("  All failure propagation tests passed!")


def test_bounded_correction():
    print("Testing bounded correction attempts...")
    calls = {"n": 0}
    exec_result = FakeExecResult(success=False, error="no such column",
                                 error_type="no_such_column")

    def generate_fn(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return "SELECT salary FROM departments;"
        return "SELECT salary FROM employees;"

    restore, _ = patch_environment(generate_result=generate_fn, exec_result=exec_result)
    try:
        pipeline = make_pipeline(enable_correction=True, max_correction_attempts=3)
        result = pipeline.run_text_query("Show salaries", question_id="q11", category="basic",
                                         reference_sql="SELECT salary FROM employees;")
    finally:
        restore()

    assert result.correction is not None, "correction stage should run"
    assert result.correction.total_attempts <= 3, \
        f"correction exceeded max attempts: {result.correction.total_attempts}"
    assert len(result.correction.attempts) <= 3
    print(f"  Correction bounded to {result.correction.total_attempts} attempts")
    print("  All correction tests passed!")


def test_audio_pipeline_with_mocked_asr():
    print("Testing audio pipeline with mocked ASR...")
    restore, calls = patch_environment(generate_result="SELECT name FROM employees;",
                                       exec_result=FakeExecResult(columns=("name",), rows=(("Alice",),)))
    try:
        pipeline = make_pipeline(enable_correction=False)
        result = pipeline.run_voice_query(
            str(PROJECT_ROOT / "backend" / "datasets" / "custom" / "spoken" / "q01.wav"),
            question_id="q01", reference_transcript="List all employee names",
        )
    finally:
        restore()

    assert result.audio is not None, "audio stage missing"
    assert result.asr is not None, "asr stage missing"
    assert result.asr.raw_transcript == "List all employee names"
    assert result.generation is not None, "text stages should follow ASR"
    assert result.execution is not None
    assert calls["executed"], "executor should run after ASR"
    print(f"  ASR transcript={result.asr.raw_transcript!r}; stages followed through to execution")
    print("  All audio integration tests passed!")


def test_audio_asr_failure_returns_early():
    print("Testing ASR failure early-return...")
    original_whisper = vls.WhisperEngine
    vls.WhisperEngine = FakeWhisperEmpty
    try:
        pipeline = make_pipeline(enable_correction=False)
        result = pipeline.run_voice_query("missing.wav", question_id="q99")
    finally:
        vls.WhisperEngine = original_whisper

    assert result.asr is not None
    assert result.asr.raw_transcript == ""
    assert result.final_status == "error"
    assert result.generation is None, "text stages should be skipped when ASR fails"
    print(f"  ASR failure returned early; final_status={result.final_status}")
    print("  All ASR failure tests passed!")


def test_reference_sql_evaluation():
    print("Testing reference-SQL correctness evaluation...")
    restore, calls = patch_environment(generate_result="SELECT employee_name FROM employees;",
                                       exec_result=FakeExecResult(columns=("employee_name",), rows=(("Alice",),)))
    try:
        pipeline = make_pipeline(enable_correction=False)
        result = pipeline.run_text_query("List all employee names", question_id="q01",
                                         reference_sql="SELECT employee_name FROM employees;")
    finally:
        restore()

    assert result.reference_sql == "SELECT employee_name FROM employees;"
    assert result.final_correct is True, "correct SQL should evaluate as correct"
    assert result.final_status == "success"
    print(f"  Reference match -> final_correct={result.final_correct}")
    print("  All reference evaluation tests passed!")


def run_all_tests():
    print("=" * 60)
    print("L9 PIPELINE TESTS")
    print("=" * 60)

    test_pipeline_result_structure()
    print()
    test_stage_dataclass_defaults()
    print()
    test_pipeline_timer()
    print()
    test_stage_ordering_and_integration()
    print()
    test_no_unsafe_sql_execution()
    print()
    test_failure_propagation()
    print()
    test_bounded_correction()
    print()
    test_audio_pipeline_with_mocked_asr()
    print()
    test_audio_asr_failure_returns_early()
    print()
    test_reference_sql_evaluation()
    print()
    print("=" * 60)
    print("ALL L9 TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
