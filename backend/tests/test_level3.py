"""Voice-LitE-SQL -- Level 3 tests: text-to-SQL baseline (Ollama mocked).

Generation/extraction correctness and execution correctness are separate:
these tests never execute SQL, they only verify the generation pipeline.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from backend.database.connection import DatabaseError
from backend.database.schema_inspector import inspect_database
from backend.llm import sql_generator
from backend.llm.ollama_client import DEFAULT_MODEL, OllamaError
from backend.llm.prompts import build_sql_prompt
from backend.llm.sql_generator import (
    extract_sql,
    generate_sql,
    validate_read_only,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "backend" / "data" / "enterprise.db"
DATASET_DIR = PROJECT_ROOT / "backend" / "datasets" / "custom"


def enterprise_question(question_id):
    questions = json.loads((DATASET_DIR / "questions.json").read_text(encoding="utf-8"))
    return next(q for q in questions if q["id"] == question_id)


def library_schema(tmp_path):
    """A database that is deliberately NOT based on models.py."""
    db = tmp_path / "library.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE authors (
            author_id   INTEGER PRIMARY KEY,
            author_name TEXT NOT NULL
        );
        CREATE TABLE books (
            book_id   INTEGER PRIMARY KEY,
            title     TEXT NOT NULL,
            author_id INTEGER REFERENCES authors(author_id)
        );
        """
    )
    conn.commit()
    conn.close()
    return inspect_database(db)


# -- prompt construction -----------------------------------------------------

def test_prompt_contains_schema():
    schema = inspect_database(DB_PATH)
    prompt = build_sql_prompt("How many employees are there?", schema)
    assert "employees" in prompt
    assert "salary" in prompt
    assert "sales" in prompt
    assert "revenue" in prompt
    assert "sales" in prompt
    assert "sale_date" in prompt


def test_prompt_contains_question():
    schema = inspect_database(DB_PATH)
    question = "What is the average salary of employees?"
    prompt = build_sql_prompt(question, schema)
    assert question in prompt


def test_prompt_not_dependent_on_models(tmp_path):
    schema = library_schema(tmp_path)
    prompt = build_sql_prompt("List all book titles", schema)
    assert "authors" in prompt
    assert "books" in prompt
    assert "title" in prompt
    assert "employees" not in prompt
    assert "sales" not in prompt


# -- SQL extraction ----------------------------------------------------------

def test_extract_plain_sql():
    assert extract_sql("SELECT COUNT(*) FROM employees;") == "SELECT COUNT(*) FROM employees;"


def test_extract_fenced_sql():
    response = "```sql\nSELECT employee_name FROM employees;\n```"
    assert extract_sql(response) == "SELECT employee_name FROM employees;"


def test_extract_sql_with_explanatory_text():
    response = (
        "Here is the SQL you asked for:\n\n"
        "SELECT employee_name, salary FROM employees;\n\n"
        "This returns every employee with their salary."
    )
    assert extract_sql(response) == "SELECT employee_name, salary FROM employees;"


def test_extract_invalid_or_empty_response():
    with pytest.raises(ValueError):
        extract_sql("")
    with pytest.raises(ValueError):
        extract_sql("   \n  ")
    with pytest.raises(ValueError):
        extract_sql("Sorry, I cannot answer that.")


# -- Ollama failure / configuration ------------------------------------------

def test_ollama_connection_failure(monkeypatch):
    def fake_generate(prompt, model=DEFAULT_MODEL, host=None, timeout=None):
        raise OllamaError("cannot reach Ollama at http://localhost:11434")

    monkeypatch.setattr(sql_generator, "generate", fake_generate)
    result = generate_sql("How many employees are there?", DB_PATH)
    assert not result.success
    assert result.generated_sql is None
    assert "ollama" in result.error.lower()


def test_model_configuration_respected(monkeypatch):
    captured = {}

    def fake_generate(prompt, model=DEFAULT_MODEL, host=None, timeout=None):
        captured["model"] = model
        captured["host"] = host
        return "SELECT 1;", {}

    monkeypatch.setattr(sql_generator, "generate", fake_generate)
    result = generate_sql(
        "Anything",
        DB_PATH,
        model="qwen3:4b",
        host="http://10.0.0.1:11434",
        timeout=5,
    )
    assert captured["model"] == "qwen3:4b"
    assert captured["host"] == "http://10.0.0.1:11434"
    assert result.model_name == "qwen3:4b"


# -- read-only validation ----------------------------------------------------

def test_read_only_select_accepted():
    validate_read_only("SELECT * FROM employees;")
    validate_read_only("WITH top AS (SELECT * FROM products) SELECT * FROM top;")


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
        "SELECT * FROM employees; DROP TABLE employees;",
    ],
)
def test_destructive_sql_rejected(bad_sql):
    with pytest.raises(ValueError):
        validate_read_only(bad_sql)


def test_non_select_sql_rejected():
    with pytest.raises(ValueError):
        validate_read_only("EXPLAIN SELECT * FROM employees;")


# -- mocked end-to-end -------------------------------------------------------

def test_mocked_end_to_end_enterprise(monkeypatch):
    q41 = enterprise_question("q41")
    expected_sql = q41["sql"].strip()

    def fake_generate(prompt, model=DEFAULT_MODEL, host=None, timeout=None):
        return f"Here is your query:\n```sql\n{expected_sql}\n```\nHope this helps!", {}

    monkeypatch.setattr(sql_generator, "generate", fake_generate)
    result = generate_sql(q41["question"], DB_PATH)

    assert result.success
    assert result.question == q41["question"]
    assert result.generated_sql == expected_sql
    assert result.model_name == DEFAULT_MODEL
    assert "Here is your query" in result.raw_response
    assert result.error is None


def test_mocked_end_to_end_second_baseline(monkeypatch):
    q42 = enterprise_question("q42")

    def fake_generate(prompt, model=DEFAULT_MODEL, host=None, timeout=None):
        return f"{q42['sql']}", {}

    monkeypatch.setattr(sql_generator, "generate", fake_generate)
    result = generate_sql(q42["question"], DB_PATH)
    assert result.success
    assert result.generated_sql == q42["sql"].strip()
