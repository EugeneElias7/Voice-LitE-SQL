"""Voice-LitE-SQL -- Level 8: execution-guided SQL self-correction.

Public API for the correction package:
- correction prompt building
- bounded correction loop with execution feedback
- correction attempt/result recording
"""

from backend.correction.correction_prompt import build_correction_prompt
from backend.correction.sql_corrector import (
    CorrectionAttempt,
    CorrectionResult,
    SQLCorrector,
    build_correction_context_text,
)

__all__ = [
    "CorrectionAttempt",
    "CorrectionResult",
    "SQLCorrector",
    "build_correction_context_text",
    "build_correction_prompt",
]