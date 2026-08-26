"""Voice-LitE-SQL -- Level 4 tests: read-only execution + evaluation + metrics."""

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from backend.database.executor import ExecutionResult, execute_sql
from backend.database.schema_inspector import inspect_database
from backend.evaluation.evaluator import (
    QueryEvaluation,
    evaluate_item,
    normalize_result,
    results_equal,
    run_evaluation,
)
from backend.evaluation.metrics import compute_metrics, metrics_by_category
from backend.llm.sql_generator import SQLGenerationResult

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "backend" / "data" / "enterprise.db"
DATASET_DIR = PROJECT_ROOT / "backend" / "datasets" / "custom"


def question(question_id):
    questions = json.loads((DATASET_DIR / "questions.json").read_text(encoding="utf-8"))
    return next(q for q in questions if q["id"] == question_id)


def db_sha256():
    return hashlib.sha256(DB_PATH.read_bytes()).hexdigest()


# -- execution ---------------------------------------------------------------

def test_simple_select_executes():
    result = execute_sql("SELECT employee_name FROM employees LIMIT 3;", DB_PATH)
    assert result.success
    assert result.columns == ["employee_name"]
    assert result.row_count == 3
    assert result.execution_time_ms >= 0
    assert result.error is None


def test_count_query_executes():
    result = execute_sql("SELECT COUNT(*) FROM employees;", DB_PATH)
    assert result.success
    assert result.row_count == 1
    assert result.rows[0][0] == 500


def test_aggregate_query_executes():
    result = execute_sql("SELECT AVG(salary) FROM employees;", DB_PATH)
    assert result.success
    assert isinstance(result.rows[0][0], float)


def test_join_query_executes():
    result = execute_sql(question("q21")["sql"], DB_PATH)
    assert result.success
    assert result.row_count == 500
    assert "employee_name" in result.columns
    assert "department_name" in result.columns


def test_with_query_allowed():
    sql = "WITH top AS (SELECT product_id FROM products LIMIT 5) SELECT COUNT(*) FROM top;"
    result = execute_sql(sql, DB_PATH)
    assert result.success
    assert result.rows[0][0] == 5


def test_invalid_sql_controlled_error():
    result = execute_sql("SELECT FROM employees;", DB_PATH)
    assert not result.success
    assert result.error_type == "syntax_error"
    assert result.error


def test_missing_column_controlled_error():
    result = execute_sql("SELECT nope FROM employees;", DB_PATH)
    assert not result.success
    assert result.error_type == "missing_column"
    assert result.error


def test_missing_table_controlled_error():
    result = execute_sql("SELECT * FROM ghosts;", DB_PATH)
    assert not result.success
    assert result.error_type == "missing_table"


@pytest.mark.parametrize(
    "bad_sql",
    [
        "INSERT INTO employees (employee_name) VALUES ('X');",
        "UPDATE employees SET salary = 0;",
        "DELETE FROM employees;",
        "DROP TABLE employees;",
        "ALTER TABLE employees ADD COLUMN x INTEGER;",
        "CREATE TABLE evil (id INTEGER);",
        "PRAGMA foreign_keys = OFF;",
        "REPLACE INTO employees (employee_id, employee_name) VALUES (999, 'X');",
        "VACUUM;",
        "ATTACH DATABASE 'x.db' AS other;",
        "DETACH DATABASE other;",
    ],
)
def test_destructive_sql_rejected(bad_sql):
    result = execute_sql(bad_sql, DB_PATH)
    assert not result.success
    assert result.error_type == "validation_error"


@pytest.mark.parametrize(
    "multi_sql",
    [
        "SELECT 1; SELECT 2;",
        "SELECT * FROM employees; DROP TABLE employees;",
        "SELECT 1; -- comment\nSELECT 2;",
    ],
)
def test_multiple_statements_rejected(multi_sql):
    result = execute_sql(multi_sql, DB_PATH)
    assert not result.success
    assert result.error_type == "validation_error"
    assert "multiple" in result.error.lower()


def test_semicolon_inside_string_allowed():
    result = execute_sql("SELECT customer_name FROM customers WHERE city = 'New; York';", DB_PATH)
    assert result.success or result.error_type != "validation_error"


def test_executor_does_not_modify_database():
    before = db_sha256()
    for sql in [
        "SELECT * FROM employees;",
        "SELECT COUNT(*) FROM sales;",
        "SELECT * FROM products WHERE price > 100;",
        "WITH x AS (SELECT 1) SELECT * FROM x;",
        "SELECT e.employee_name, d.department_name FROM employees e JOIN departments d ON e.department_id = d.department_id;",
    ]:
        execute_sql(sql, DB_PATH)
    assert db_sha256() == before


# -- normalization / comparison ----------------------------------------------

def test_result_normalization():
    result = execute_sql("SELECT employee_name, salary FROM employees LIMIT 1;", DB_PATH)
    columns, rows = normalize_result(result)
    assert columns == ["employee_name", "salary"]
    assert isinstance(rows[0][0], str)
    assert rows[0][0] == rows[0][0].strip()
    assert isinstance(rows[0][1], float)


def test_results_equal_column_order_agnostic():
    ref_sql = "SELECT employee_id, employee_name FROM employees ORDER BY employee_id LIMIT 5;"
    gen_sql = "SELECT employee_name, employee_id FROM employees ORDER BY employee_id LIMIT 5;"
    ref = execute_sql(ref_sql, DB_PATH)
    gen = execute_sql(gen_sql, DB_PATH)
    assert results_equal(ref_sql, ref, gen_sql, gen)


def test_results_equal_unordered_and_unequal():
    ref_sql = "SELECT employee_name FROM employees WHERE salary > 100000;"
    same_sql = "SELECT employee_name FROM employees WHERE salary > 100000;"
    diff_sql = "SELECT employee_name FROM employees WHERE salary > 200000;"
    assert results_equal(ref_sql, execute_sql(ref_sql, DB_PATH), same_sql, execute_sql(same_sql, DB_PATH))
    assert not results_equal(
        ref_sql, execute_sql(ref_sql, DB_PATH), diff_sql, execute_sql(diff_sql, DB_PATH)
    )


def test_reference_and_generated_equivalent():
    q41 = question("q41")
    ref = execute_sql(q41["sql"], DB_PATH)
    gen = execute_sql("select count(*) as employee_count from employees", DB_PATH)
    assert results_equal(q41["sql"], ref, "select count(*) as employee_count from employees", gen)


# -- evaluation --------------------------------------------------------------

def test_evaluation_small_subset():
    items = [question("q01"), question("q41"), question("q21")]

    def gen(question):
        for item in items:
            if item["question"] == question:
                return SQLGenerationResult(question, item["sql"].strip(), "mocked", "", True, None)
        return SQLGenerationResult(question, None, "mocked", "", False, "unknown")

    evaluations = run_evaluation(items, gen, DB_PATH)
    assert len(evaluations) == 3
    assert all(e.generation_success for e in evaluations)
    assert all(e.execution_success for e in evaluations)
    assert all(e.correctness for e in evaluations)
    assert evaluations[1].question_id == "q41"


def test_evaluation_generation_failure():
    items = [question("q01")]

    def gen(question):
        return SQLGenerationResult(question, None, "mocked", "", False, "ollama error: boom")

    evaluation = run_evaluation(items, gen, DB_PATH)[0]
    assert not evaluation.generation_success
    assert not evaluation.execution_success
    assert not evaluation.correctness
    assert evaluation.execution_error_type == "generation_error"


def test_evaluation_execution_failure():
    items = [question("q01")]

    def gen(question):
        return SQLGenerationResult(question, "SELECT nope FROM employees;", "mocked", "", True, None)

    evaluation = run_evaluation(items, gen, DB_PATH)[0]
    assert evaluation.generation_success
    assert not evaluation.execution_success
    assert not evaluation.correctness
    assert evaluation.execution_error_type == "missing_column"


def test_evaluation_incorrect_but_executable():
    items = [question("q41")]

    def gen(question):
        return SQLGenerationResult(question, "SELECT COUNT(*) FROM departments;", "mocked", "", True, None)

    evaluation = run_evaluation(items, gen, DB_PATH)[0]
    assert evaluation.generation_success
    assert evaluation.execution_success
    assert not evaluation.correctness
    assert evaluation.execution_error is None


# -- metrics -----------------------------------------------------------------

def _make_evaluation(correctness, generation_success=True, execution_success=True, latency=5.0):
    return QueryEvaluation(
        question_id="q",
        category="SELECT",
        question="?",
        generation_success=generation_success,
        execution_success=execution_success,
        correctness=correctness,
        generated_sql="SELECT 1;",
        reference_sql="SELECT 1;",
        execution_error=None,
        execution_error_type=None,
        execution_time_ms=latency,
    )


def test_metrics_calculate():
    evaluations = [
        _make_evaluation(True, latency=10.0),
        _make_evaluation(True, latency=20.0),
        _make_evaluation(False, latency=30.0),
        _make_evaluation(False, execution_success=False),
        _make_evaluation(False, generation_success=False, execution_success=False),
    ]
    metrics = compute_metrics(evaluations)
    assert metrics["total_questions"] == 5
    assert metrics["generation_success_rate"] == pytest.approx(0.8)
    assert metrics["execution_success_rate"] == pytest.approx(0.6)
    assert metrics["execution_accuracy"] == pytest.approx(0.4)
    assert metrics["sql_execution_error_rate"] == pytest.approx(0.4)
    assert metrics["average_execution_latency_ms"] == pytest.approx(20.0)
    assert metrics["median_execution_latency_ms"] == pytest.approx(20.0)


def test_metrics_by_category():
    evaluations = [
        _make_evaluation(True, latency=10.0),
        _make_evaluation(False),
        QueryEvaluation(
            question_id="q", category="WHERE", question="?", generation_success=True,
            execution_success=True, correctness=True, generated_sql="s", reference_sql="r",
            execution_error=None, execution_error_type=None, execution_time_ms=1.0,
        ),
    ]
    by_category = metrics_by_category(evaluations)
    assert set(by_category) == {"SELECT", "WHERE"}
    assert by_category["SELECT"]["total_questions"] == 2
    assert by_category["WHERE"]["execution_accuracy"] == pytest.approx(1.0)
