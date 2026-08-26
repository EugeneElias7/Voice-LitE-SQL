"""Voice-LitE-SQL -- Level 8: execution-guided SQL self-correction loop.

Implements a bounded retry loop that:
1. Executes SQL via the L4 read-only executor
2. On failure/incorrect result, builds a correction prompt with error context
3. Sends to Qwen for a corrected SQL
4. Repeats until success or max attempts reached
"""

import time
from dataclasses import dataclass, field
from typing import Optional

from backend.correction.correction_prompt import build_correction_prompt
from backend.database.executor import ExecutionResult, execute_sql
from backend.evaluation.evaluator import results_equal
from backend.llm.ollama_client import OllamaError, generate
from backend.llm.sql_generator import extract_sql, validate_read_only
from backend.retrieval import RetrievalResult


@dataclass
class CorrectionAttempt:
    """Record of one correction attempt."""

    attempt_number: int
    sql: str
    prompt: str
    raw_response: str
    execution_result: Optional[ExecutionResult] = None
    execution_error: Optional[str] = None
    execution_error_type: Optional[str] = None
    execution_time_ms: float = 0.0
    is_correct: bool = False


@dataclass
class CorrectionResult:
    """Complete record of the correction process for one question."""

    question_id: str
    question: str
    category: str
    reference_sql: str
    original_sql: str
    retrieval: RetrievalResult
    attempts: list = field(default_factory=list)
    final_sql: Optional[str] = None
    final_correct: bool = False
    total_attempts: int = 0
    rescued: bool = False  # L7 wrong -> L8 correct
    harmed: bool = False  # L7 correct -> L8 wrong


class SQLCorrector:
    """Bounded SQL self-correction loop using execution feedback."""

    def __init__(
        self,
        db_path: str,
        model: str = "qwen2.5-coder:1.5b",
        max_attempts: int = 3,
        timeout: int = 120,
    ):
        self.db_path = db_path
        self.model = model
        self.max_attempts = max_attempts
        self.timeout = timeout

    def build_reference_result_text(self, reference_sql: str, db_path: str) -> str:
        """Generate a human-readable expected result for evaluation mode.

        Only used in evaluation where a reference SQL is available.
        Production callers omit ``reference_result_text``.
        """
        ref_result = execute_sql(reference_sql, db_path)
        if not ref_result.success or not ref_result.rows:
            return ""
        cols = ", ".join(ref_result.columns) if ref_result.columns else "no columns"
        row_count = len(ref_result.rows)
        # Show first few rows
        sample_rows = ref_result.rows[:5]
        rows_text = "\n".join(str(row) for row in sample_rows)
        if row_count > 5:
            rows_text += f"\n... ({row_count - 5} more rows)"
        return f"Columns: {cols}\nRow count: {row_count}\nSample rows:\n{rows_text}"

    def correct(
        self,
        question: str,
        category: str,
        question_id: str,
        reference_sql: str,
        original_sql: str,
        retrieval: RetrievalResult,
        schema_context_text: str,
        reference_result_text: str = "",
        is_l7_correct: bool = False,
    ) -> CorrectionResult:
        """Run the bounded correction loop.

        Parameters
        ----------
        question:
            The natural-language question.
        category:
            Question category (SELECT, WHERE, JOIN, etc.).
        question_id:
            Unique question identifier.
        reference_sql:
            The ground-truth reference SQL from the dataset.
        original_sql:
            The initial L7-generated SQL (first attempt).
        retrieval:
            The L7 retrieval result with schema context.
        schema_context_text:
            Formatted schema context for the prompt.
        reference_result_text:
            Optional human-readable expected result (evaluation mode only).
        is_l7_correct:
            Whether the original L7 SQL was already correct.

        Returns
        -------
        CorrectionResult with full attempt history.
        """
        result = CorrectionResult(
            question_id=question_id,
            question=question,
            category=category,
            reference_sql=reference_sql,
            original_sql=original_sql,
            retrieval=retrieval,
        )

        current_sql = original_sql
        attempt = 1
        seen_sql = {original_sql}

        while attempt <= self.max_attempts:
            # Execute current SQL
            exec_started = time.perf_counter()
            exec_result = execute_sql(current_sql, self.db_path)
            exec_time_ms = round((time.perf_counter() - exec_started) * 1000.0, 3)

            attempt_record = CorrectionAttempt(
                attempt_number=attempt,
                sql=current_sql,
                prompt="",  # filled below
                raw_response="",
                execution_result=exec_result,
                execution_error=exec_result.error,
                execution_error_type=exec_result.error_type,
                execution_time_ms=exec_time_ms,
            )

            # Check for success
            is_correct = False
            if exec_result.success:
                ref_result = execute_sql(reference_sql, self.db_path)
                if ref_result.success:
                    is_correct = results_equal(
                        reference_sql, ref_result, current_sql, exec_result
                    )

            attempt_record.is_correct = is_correct
            result.attempts.append(attempt_record)

            if is_correct:
                result.final_sql = current_sql
                result.final_correct = True
                result.total_attempts = attempt
                result.rescued = not is_l7_correct and is_correct
                result.harmed = is_l7_correct and not is_correct
                break

            # Build correction prompt
            exec_error = exec_result.error or ""
            error_type = exec_result.error_type or "incorrect_result"

            prompt = build_correction_prompt(
                question=question,
                current_sql=current_sql,
                execution_error=exec_error,
                error_type=error_type,
                schema_context_text=schema_context_text,
                reference_result_text=reference_result_text,
            )
            attempt_record.prompt = prompt

            # Call LLM for correction
            try:
                raw_response, _ = generate(prompt, model=self.model, timeout=self.timeout)
                attempt_record.raw_response = raw_response
            except Exception as exc:  # OllamaError or connection error
                attempt_record.execution_error = f"LLM error: {exc}"
                attempt_record.execution_error_type = "llm_error"
                break

            # Extract and validate SQL
            try:
                corrected_sql = extract_sql(raw_response)
                validate_read_only(corrected_sql)
            except ValueError as exc:
                attempt_record.execution_error = f"SQL extraction/validation failed: {exc}"
                attempt_record.execution_error_type = "validation_error"
                break

            # Never blindly retry the same SQL: if the model echoes back a
            # statement we have already executed, stop instead of looping.
            if corrected_sql in seen_sql:
                attempt_record.execution_error = (
                    "no progress: corrected SQL repeats a previously attempted statement"
                )
                attempt_record.execution_error_type = "no_progress"
                break
            seen_sql.add(corrected_sql)
            current_sql = corrected_sql

            attempt += 1

        # If loop exhausted without success
        result.total_attempts = len(result.attempts)
        if result.final_sql is None and result.attempts:
            result.final_sql = result.attempts[-1].sql
            result.final_correct = False
            result.harmed = is_l7_correct and not result.final_correct

        return result


def build_correction_context_text(retrieval: RetrievalResult) -> str:
    """Format the L7 retrieval result into the schema context for correction prompts."""
    from backend.retrieval.schema_retriever import format_schema_context
    return format_schema_context(retrieval.items)