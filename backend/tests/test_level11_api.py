"""Voice-LitE-SQL -- Level 11: FastAPI endpoint tests.

Uses a fake pipeline service so tests never touch the embedder, Ollama or
Whisper. Endpoint behaviour, response shape and the SSE progress stream are
asserted against the frozen PipelineResult structure.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app, STAGE_META, TEXT_STAGES
from backend.api.service import set_service
from backend.pipeline.pipeline_result import PipelineTimer
from backend.pipeline.pipeline_result import (
    ASRStage,
    ExecutionStage,
    GenerationStage,
    NLPStage,
    NormalizationStage,
    PipelineResult,
    RetrievalStage,
    ValidationStage,
)

DB_PATH = str(Path(__file__).resolve().parents[2] / "backend" / "data" / "enterprise.db")


class FakePipelineService:
    """Deterministic pipeline stand-in returning structured results."""

    db_path = DB_PATH
    index_dir = "evaluation/index/l9"
    _pipeline = None
    fail_next = False

    @property
    def database_name(self):
        return "enterprise"

    def _result(self, question, mode="text"):
        result = PipelineResult(category="", reference_sql="")
        result.question_id = ""
        result.normalization = NormalizationStage(
            original_text=question,
            normalized_text=question,
            token_decisions=[
                {"original": "employees", "replacement": "employees",
                 "confidence": 1.0, "applied": False, "strategy": "none",
                 "reason": "exact_match", "scores": {}, "candidate": None}
            ],
            latency_ms=3.0,
        )
        result.nlp = NLPStage(
            intent={
                "primary_intent": "AGGREGATE",
                "join_required": False,
                "aggregation_required": True,
                "grouping_required": False,
                "ordering_required": False,
                "subquery_likely": False,
                "confidence": 1.0,
            },
            linked_entities=[
                {"entity_type": "table", "table": "employees", "column": "",
                 "match_type": "exact", "matched_text": "employees", "confidence": 1.0}
            ],
            phrase_matches=[
                {"phrase": "how many", "entity_type": "concept", "table": "",
                 "column": "", "match_type": "concept", "score": 1.0,
                 "concept": "aggregation:COUNT"}
            ],
            reranked=True,
            relationship_decisions=[
                {"source_table": "orders", "source_column": "employee_id",
                 "target_table": "employees", "target_column": "employee_id",
                 "required": False, "reason": "Default", "confidence": 0.5}
            ],
            filtered_items_count=3,
            latency_ms=10.0,
        )
        result.retrieval = RetrievalStage(
            query_text=question,
            retrieved_items=[
                {"doc_type": "column", "doc_id": "column:employees.employee_id",
                 "table": "employees", "column": "employee_id",
                 "text": "COLUMN: employees.employee_id", "score": 0.8,
                 "distance": 0.2, "source": "retrieval"}
            ],
            top_k=5,
            latency_ms=5.0,
        )
        result.generation = GenerationStage(
            raw_response="SELECT count(*) FROM employees",
            generated_sql="SELECT count(*) FROM employees",
            prompt_length=100,
            latency_ms=20.0,
        )
        result.validation = ValidationStage(
            is_valid=True,
            issues=[],
            tables_used=["employees"],
            columns_used=[],
            joins=[],
            has_aggregation=True,
            has_group_by=False,
            latency_ms=2.0,
        )
        result.execution = ExecutionStage(
            success=True,
            rows=[{"count(*)": 500}],
            columns=["count(*)"],
            error=None,
            error_type=None,
            execution_time_ms=1.0,
            latency_ms=2.0,
        )
        result.final_sql = "SELECT count(*) FROM employees"
        result.final_result_rows = [{"count(*)": 500}]
        result.final_correct = False
        result.final_status = "partial"
        result.stage_latencies = {
            "normalization": 3.0, "nlp": 10.0, "retrieval": 5.0,
            "generation": 20.0, "validation": 2.0, "execution": 2.0,
        }
        result.total_latency_ms = 42.0
        return result

    def run_text_query(self, question, category="", question_id=""):
        if self.fail_next:
            raise RuntimeError("simulated pipeline failure")
        result = self._result(question, mode="text")
        result.audio = None
        result.asr = None
        return result

    def run_voice_query(self, audio_path, category=""):
        if self.fail_next:
            raise RuntimeError("simulated pipeline failure")
        result = self._result("How many employees are there?", mode="voice")
        result.audio = None
        result.asr = ASRStage(
            raw_transcript="How many employees are there?",
            model_name="faster-whisper-small",
            wer=None,
            latency_ms=500.0,
        )
        result.stage_latencies["asr"] = 500.0
        result.total_latency_ms = 542.0
        return result


@pytest.fixture(autouse=True)
def use_fake_service():
    fake = FakePipelineService()
    set_service(fake)
    yield fake
    set_service(None)


def _client():
    return TestClient(app)


def test_health_ok():
    response = _client().get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "enterprise"


def test_status_shape():
    body = _client().get("/api/status").json()
    for component in ("backend", "database", "ollama", "model", "whisper", "chroma", "schema"):
        assert component in body
    assert body["model"]["name"] == "qwen2.5-coder:1.5b"


def test_schema_shape():
    body = _client().get("/api/schema").json()
    assert body["database"] == "enterprise"
    names = [t["name"] for t in body["tables"]]
    assert "employees" in names
    employees = next(t for t in body["tables"] if t["name"] == "employees")
    assert employees["row_count"] == 500
    assert any(c["name"] == "employee_id" for c in employees["columns"])
    assert any(c["primary_key_position"] == 1 for c in employees["columns"])


def test_demo_questions_sourced_from_file():
    body = _client().get("/api/demo-questions").json()
    assert len(body["questions"]) >= 4
    assert all(q["question"] for q in body["questions"])


def test_text_query_returns_enriched_pipeline_result():
    response = _client().post("/api/query", json={"question": "How many employees are there?"})
    assert response.status_code == 200
    body = response.json()
    assert body["final_status"] == "partial"
    assert body["generation"]["generated_sql"] == "SELECT count(*) FROM employees"
    assert body["execution"]["success"] is True
    assert body["execution"]["rows"] == [{"count(*)": 500}]
    assert body["nlp"]["intent"]["primary_intent"] == "AGGREGATE"
    assert body["input"]["mode"] == "text"
    assert body["input"]["question"] == "How many employees are there?"
    assert body["total_latency_ms"] == 42.0


def test_text_query_rejects_empty_question():
    response = _client().post("/api/query", json={"question": "   "})
    assert response.status_code == 422


def test_text_query_failure_returns_structured_error(use_fake_service):
    use_fake_service.fail_next = True
    response = _client().post("/api/query", json={"question": "boom"})
    assert response.status_code == 500
    assert "pipeline failed" in response.json()["detail"]


def test_voice_query_returns_transcript_and_result():
    files = {"file": ("question.webm", b"fake-audio-bytes", "audio/webm")}
    response = _client().post("/api/voice-query", files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["asr"]["raw_transcript"] == "How many employees are there?"
    assert body["input"]["mode"] == "voice"
    assert body["input"]["transcript"] == "How many employees are there?"
    assert body["execution"]["success"] is True


def test_sse_stream_emits_real_stages_and_result():
    events = []
    with _client().stream(
        "POST", "/api/query/stream", json={"question": "How many employees are there?"}
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    names = [e["event"] for e in events]
    assert names[0] == "pipeline_started"
    assert names[-1] == "pipeline_completed"
    started = events[0]
    assert started["mode"] == "text"
    keys = [s["key"] for s in started["stages"]]
    assert keys == [s["key"] for s in TEXT_STAGES]
    for e in events[1:-1]:
        assert e["event"] == "stage_completed"
        assert e["stage"] in keys
        assert isinstance(e["latency_ms"], (int, float))
    completed = events[-1]
    assert completed["result"]["generation"]["generated_sql"] == "SELECT count(*) FROM employees"


def test_sse_emits_pipeline_error(use_fake_service):
    use_fake_service.fail_next = True
    events = []
    with _client().stream("POST", "/api/query/stream", json={"question": "boom"}) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    assert events[-1]["event"] == "pipeline_error"
    assert "simulated" in events[-1]["error"]


def test_progress_hook_restores_pipeline_timer():
    from backend.api.progress import install_progress_hook

    original = PipelineTimer.__exit__
    with install_progress_hook(lambda stage, ms: None):
        assert PipelineTimer.__exit__ is not original
    assert PipelineTimer.__exit__ is original