"""Voice-LitE-SQL -- Level 9: Full end-to-end voice-to-SQL pipeline.

Unified orchestration layer combining L5 (ASR), L6 (phonetic normalization),
L7 (schema retrieval), L8.1 (NLP optimization), L4 (execution), and L8 (correction).
"""

from backend.pipeline.pipeline_result import (
    PipelineResult,
    StageResult,
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
from backend.pipeline.voice_lite_sql import (
    VoiceLitESQLPipeline,
    PipelineConfig,
    run_text_query,
    run_voice_query,
)

__all__ = [
    "PipelineResult",
    "StageResult",
    "AudioStage",
    "ASRStage",
    "NormalizationStage",
    "NLPStage",
    "RetrievalStage",
    "GenerationStage",
    "ValidationStage",
    "ExecutionStage",
    "CorrectionStage",
    "VoiceLitESQLPipeline",
    "PipelineConfig",
    "run_text_query",
    "run_voice_query",
]