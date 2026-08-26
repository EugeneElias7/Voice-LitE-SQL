"""Voice-LitE-SQL -- Level 9: Structured pipeline result types.

Each stage produces a structured result with technical diagnostics.
No chain-of-thought or verbose internal state is exposed.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
import time


@dataclass
class StageResult:
    """Generic stage result with timing and status."""
    stage_name: str
    success: bool
    latency_ms: float
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "stage": self.stage_name,
            "success": self.success,
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class AudioStage:
    """Audio capture/input stage."""
    audio_path: str
    duration_seconds: Optional[float] = None
    capture_status: str = "loaded"
    latency_ms: float = 0.0


@dataclass
class ASRStage:
    """ASR transcription stage."""
    raw_transcript: str
    model_name: str = "faster-whisper-small"
    wer: Optional[float] = None
    reference_transcript: Optional[str] = None
    latency_ms: float = 0.0


@dataclass
class NormalizationStage:
    """L6 phonetic normalization stage."""
    original_text: str
    normalized_text: str
    token_decisions: List[Dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0


@dataclass
class NLPStage:
    """L8.1 NLP processing stage."""
    intent: Dict[str, Any]
    linked_entities: List[Dict[str, Any]]
    phrase_matches: List[Dict[str, Any]]
    reranked: bool = False
    relationship_decisions: List[Dict[str, Any]] = field(default_factory=list)
    filtered_items_count: int = 0
    latency_ms: float = 0.0


@dataclass
class RetrievalStage:
    """L7 schema retrieval stage."""
    query_text: str
    retrieved_items: List[Dict[str, Any]]
    top_k: int
    latency_ms: float = 0.0


@dataclass
class GenerationStage:
    """Qwen SQL generation stage."""
    raw_response: str
    generated_sql: str
    prompt_length: int
    latency_ms: float = 0.0


@dataclass
class ValidationStage:
    """SQL structural validation stage."""
    is_valid: bool
    issues: List[Dict[str, Any]]
    tables_used: List[str]
    columns_used: List[str]
    joins: List[Dict[str, Any]]
    has_aggregation: bool
    has_group_by: bool
    latency_ms: float = 0.0


@dataclass
class ExecutionStage:
    """L4 SQL execution stage."""
    success: bool
    rows: List[Dict[str, Any]] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    error: Optional[str] = None
    error_type: Optional[str] = None
    execution_time_ms: float = 0.0
    latency_ms: float = 0.0


@dataclass
class CorrectionStage:
    """L8 execution-guided correction stage."""
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    total_attempts: int = 0
    rescued: bool = False
    harmed: bool = False
    final_correct: bool = False
    latency_ms: float = 0.0


@dataclass
class PipelineResult:
    """Complete end-to-end pipeline result."""
    question_id: Optional[str] = None
    category: Optional[str] = None
    reference_sql: Optional[str] = None

    # Stage results
    audio: Optional[AudioStage] = None
    asr: Optional[ASRStage] = None
    normalization: Optional[NormalizationStage] = None
    nlp: Optional[NLPStage] = None
    retrieval: Optional[RetrievalStage] = None
    generation: Optional[GenerationStage] = None
    validation: Optional[ValidationStage] = None
    execution: Optional[ExecutionStage] = None
    correction: Optional[CorrectionStage] = None

    # Final results
    final_sql: Optional[str] = None
    final_result_rows: List[Dict[str, Any]] = field(default_factory=list)
    final_correct: bool = False
    final_status: str = "pending"  # "success" | "error" | "partial"

    # Timing
    stage_latencies: Dict[str, float] = field(default_factory=dict)
    total_latency_ms: float = 0.0
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self):
        return {
            "question_id": self.question_id,
            "category": self.category,
            "reference_sql": self.reference_sql,
            "audio": self.audio.__dict__ if self.audio else None,
            "asr": self.asr.__dict__ if self.asr else None,
            "normalization": self.normalization.__dict__ if self.normalization else None,
            "nlp": self.nlp.__dict__ if self.nlp else None,
            "retrieval": self.retrieval.__dict__ if self.retrieval else None,
            "generation": self.generation.__dict__ if self.generation else None,
            "validation": self.validation.__dict__ if self.validation else None,
            "execution": self.execution.__dict__ if self.execution else None,
            "correction": self.correction.__dict__ if self.correction else None,
            "final_sql": self.final_sql,
            "final_result_rows": self.final_result_rows,
            "final_correct": self.final_correct,
            "final_status": self.final_status,
            "stage_latencies": {k: round(v, 2) for k, v in self.stage_latencies.items()},
            "total_latency_ms": round(self.total_latency_ms, 2),
            "started_at": self.started_at,
        }


class PipelineTimer:
    """Context manager for timing pipeline stages."""
    def __init__(self, result: PipelineResult, stage_name: str):
        self.result = result
        self.stage_name = stage_name
        self.start_time = 0.0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (time.perf_counter() - self.start_time) * 1000.0
        self.result.stage_latencies[self.stage_name] = round(elapsed, 2)
        self.result.total_latency_ms = sum(self.result.stage_latencies.values())