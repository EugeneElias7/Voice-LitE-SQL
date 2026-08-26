"""Voice-LitE-SQL -- Level 11: real-time pipeline progress instrumentation.

The frozen L9 pipeline code is never modified. For the lifetime of a single
streaming request we wrap ``PipelineTimer.__exit__`` at runtime so that real
per-stage completion events (stage name + measured latency) are pushed to the
frontend as they happen. When the last streaming request finishes the class is
restored to its original behaviour.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable, List

from backend.pipeline.pipeline_result import PipelineTimer

_HOOKS: List[Callable[[str, float], None]] = []
_LOCK = threading.Lock()
_ORIGINAL_EXIT = PipelineTimer.__exit__  # captured from the frozen class once


def _patched_exit(timer: PipelineTimer, exc_type, exc_val, exc_tb):
    _ORIGINAL_EXIT(timer, exc_type, exc_val, exc_tb)
    latency = timer.result.stage_latencies.get(timer.stage_name, 0.0)
    for hook in list(_HOOKS):
        try:
            hook(timer.stage_name, round(float(latency), 2))
        except Exception:  # pragma: no cover - never break the pipeline
            pass


@contextmanager
def install_progress_hook(hook: Callable[[str, float], None]):
    """Temporarily subscribe ``hook(stage_name, latency_ms)`` to stage events.

    The patch is installed once for the first active subscriber and torn down
    after the last one, so concurrent streaming requests all receive events.
    """
    with _LOCK:
        was_active = bool(_HOOKS)
        _HOOKS.append(hook)
        if not was_active:
            PipelineTimer.__exit__ = _patched_exit
    try:
        yield
    finally:
        with _LOCK:
            if hook in _HOOKS:
                _HOOKS.remove(hook)
            if not _HOOKS and PipelineTimer.__exit__ is _patched_exit:
                PipelineTimer.__exit__ = _ORIGINAL_EXIT