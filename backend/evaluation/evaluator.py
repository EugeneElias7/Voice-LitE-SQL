"""Voice-LitE-SQL -- Level 4: evaluation of generated SQL vs reference SQL.

Compares semantic execution results (normalized) rather than SQL strings.
"""

import re
from dataclasses import dataclass

from backend.database.executor import ExecutionResult, execute_sql

ORDER_BY_PATTERN = re.compile(r"\bORDER\s+BY\b", re.IGNORECASE)


@dataclass
class QueryEvaluation:
    question_id: str
    category: str
    question: str
    generation_success: bool
    execution_success: bool
    correctness: bool
    generated_sql: str
    reference_sql: str
    execution_error: str
    execution_error_type: str
    execution_time_ms: float

    def to_dict(self):
        return {
            "question_id": self.question_id,
            "category": self.category,
            "question": self.question,
            "generation_success": self.generation_success,
            "execution_success": self.execution_success,
            "correctness": self.correctness,
            "generated_sql": self.generated_sql,
            "reference_sql": self.reference_sql,
            "execution_error": self.execution_error,
            "execution_error_type": self.execution_error_type,
            "execution_time_ms": self.execution_time_ms,
        }


# ---------------------------------------------------------------------------
# Result normalization
# ---------------------------------------------------------------------------
def normalize_cell(value):
    """Deterministic cell normalization: NULL, numeric, string."""
    if value is None:
        return None
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, str):
        return value.strip()
    return value


def normalize_result(result):
    """Return (normalized columns, normalized rows)."""
    columns = [c.lower().strip() for c in (result.columns or [])]
    rows = [[normalize_cell(v) for v in row] for row in (result.rows or [])]
    return columns, rows


def has_order_by(sql):
    return bool(ORDER_BY_PATTERN.search(sql or ""))


def results_equal(reference_sql, reference_result, generated_sql, generated_result):
    """Compare two ExecutionResults semantically.

    - column names are compared as sets (order-agnostic), rows are reordered
      to match the sorted column order on both sides
    - unordered queries compare as sorted row multisets
    - ordered queries (ORDER BY present) compare row sequences in order
    """
    if not (reference_result.success and generated_result.success):
        return False
    ref_columns, ref_rows = normalize_result(reference_result)
    gen_columns, gen_rows = normalize_result(generated_result)
    if set(ref_columns) != set(gen_columns):
        return False

    def reorder(columns, rows):
        index = {name: i for i, name in enumerate(columns)}
        ordered = sorted(columns)
        return [[row[index[name]] for name in ordered] for row in rows]

    ref_norm = reorder(ref_columns, ref_rows)
    gen_norm = reorder(gen_columns, gen_rows)

    if not (has_order_by(reference_sql) or has_order_by(generated_sql)):
        ref_norm = sorted(ref_norm)
        gen_norm = sorted(gen_norm)
    return ref_norm == gen_norm


# ---------------------------------------------------------------------------
# Evaluation pipeline
# ---------------------------------------------------------------------------
def evaluate_item(item, generator_fn, db_path):
    """Evaluate one question item with the given generation function."""
    question = item["question"]
    reference_sql = item["sql"]
    generated = generator_fn(question)

    evaluation = QueryEvaluation(
        question_id=item.get("id", ""),
        category=item.get("category", ""),
        question=question,
        generation_success=generated.success,
        execution_success=False,
        correctness=False,
        generated_sql=generated.generated_sql if generated.success else None,
        reference_sql=reference_sql,
        execution_error=None,
        execution_error_type=None,
        execution_time_ms=0.0,
    )
    if not generated.success:
        evaluation.execution_error = generated.error
        evaluation.execution_error_type = "generation_error"
        return evaluation

    reference = execute_sql(reference_sql, db_path)
    executed = execute_sql(generated.generated_sql, db_path)
    evaluation.execution_time_ms = executed.execution_time_ms
    if not executed.success:
        evaluation.execution_error = executed.error
        evaluation.execution_error_type = executed.error_type
        return evaluation

    evaluation.execution_success = True
    if reference.success:
        evaluation.correctness = results_equal(
            reference_sql, reference, generated.generated_sql, executed
        )
    return evaluation


def run_evaluation(questions, generator_fn, db_path):
    """Evaluate a list of question items; returns list[QueryEvaluation]."""
    return [evaluate_item(item, generator_fn, db_path) for item in questions]
