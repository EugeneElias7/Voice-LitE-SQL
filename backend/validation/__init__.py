"""Voice-LitE-SQL -- Level 8.1: SQL Structural Validation.

Validates generated SQL for structural correctness before execution.
"""

from backend.validation.sql_structure_validator import (
    SQLStructureValidator,
    ValidationResult,
    validate_sql_structure,
)

__all__ = [
    "SQLStructureValidator",
    "ValidationResult",
    "validate_sql_structure",
]