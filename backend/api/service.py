"""Voice-LitE-SQL -- Level 11: pipeline service singleton.

Lazily builds and reuses a single ``VoiceLitESQLPipeline`` for the active
demonstration database so consecutive requests share the ASR engine, the
phonetic vocabulary and the ChromaDB index.
"""

from __future__ import annotations

import threading
from typing import Optional

from backend.pipeline.pipeline_result import PipelineResult
import os

from backend.pipeline.voice_lite_sql import (
    DEFAULT_DB,
    DEFAULT_INDEX_DIR,
    PipelineConfig,
    VoiceLitESQLPipeline,
)


class PipelineService:
    """Thread-safe holder for the shared pipeline instance."""

    def __init__(self, db_path: str = str(DEFAULT_DB),
                 index_dir: str = str(DEFAULT_INDEX_DIR)):
        self.db_path = db_path
        self.index_dir = index_dir
        self._pipeline: Optional[VoiceLitESQLPipeline] = None
        self._lock = threading.RLock()
        # Render free has no torch - use fake embedder via env
        self._fake_embedder = os.getenv("FAKE_EMBEDDER", "false").lower() in ("1", "true", "yes")

    @property
    def database_name(self) -> str:
        from pathlib import Path
        return Path(self.db_path).stem

    def pipeline(self) -> VoiceLitESQLPipeline:
        """Return the shared pipeline, building it lazily on first use."""
        with self._lock:
            if self._pipeline is None:
                self._pipeline = VoiceLitESQLPipeline(
                    PipelineConfig(db_path=self.db_path, index_dir=self.index_dir, fake_embedder=self._fake_embedder)
                )
            return self._pipeline

    def reset(self) -> None:
        """Drop the shared instance (used by tests / config changes)."""
        with self._lock:
            self._pipeline = None

    def run_text_query(self, question: str, category: str = "",
                       question_id: str = "") -> PipelineResult:
        return self.pipeline().run_text_query(
            question, question_id=question_id or None, category=category or None
        )

    def run_voice_query(self, audio_path: str, category: str = "") -> PipelineResult:
        return self.pipeline().run_voice_query(
            audio_path, category=category or None
        )


_service: Optional[PipelineService] = None
_service_lock = threading.Lock()


def get_service() -> PipelineService:
    """Return the application-wide service instance."""
    global _service
    with _service_lock:
        if _service is None:
            _service = PipelineService()
        return _service


def set_service(service: PipelineService) -> None:
    """Replace the application-wide service (used by tests / overrides)."""
    global _service
    with _service_lock:
        _service = service