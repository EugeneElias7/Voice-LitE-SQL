"""Voice-LitE-SQL -- Level 8 tests: execution-guided SQL self-correction.

Covers the correction package with a mocked LLM so the correction loop
is fully exercised without a live Ollama dependency.
"""

import sqlite3
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from backend.correction import (
    CorrectionAttempt,
    CorrectionResult,
    SQLCorrector,
    build_correction_context_text,
    build_correction_prompt,
)
from backend.database.executor import execute_sql
from backend.retrieval import (
    CountVectorEmbedder,
    SchemaRetriever,
    generate_schema_documents,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "backend" / "data" / "enterprise.db"

TEMP_SCHEMA_SQL = """
CREATE TABLE authors (
    author_id   INTEGER PRIMARY KEY,
    author_name TEXT NOT NULL,
    birth_year  INTEGER
);
CREATE TABLE books (
    book_id    INTEGER PRIMARY KEY,
    title      TEXT NOT NULL,
    author_id  INTEGER REFERENCES authors(author_id),
    pages      INTEGER DEFAULT 0
);
"""

FAKE_EMBEDDER = CountVectorEmbedder(dimensions=384)


def make_temp_db(tmp_path, name="books.db", sql=TEMP_SCHEMA_SQL):
    db = tmp_path / name
    conn = sqlite3.connect(str(db))
    conn.executescript(sql)
    conn.commit()
    conn.close()
    return db


def new_persist_dir(tmp_path):
    return tmp_path / f"chroma-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# 1. Correction prompt building
# ---------------------------------------------------------------------------

def test_correction_prompt_contains_question():
    prompt = build_correction_prompt(
        question="List all employees",
        current_sql="SELECT name FROM employees;",
        execution_error="no such column: name",
        error_type="missing_column",
        schema_context_text="COLUMN: employees.employee_name",
        reference_result_text="",
    )
    assert "List all employees" in prompt
    assert "ORIGINAL QUESTION" in prompt


def test_correction_prompt_contains_current_sql():
    prompt = build_correction_prompt(
        question="List all employees",
        current_sql="SELECT name FROM employees;",
        execution_error="no such column: name",
        error_type="missing_column",
        schema_context_text="COLUMN: employees.employee_name",
        reference_result_text="",
    )
    assert "SELECT name FROM employees" in prompt
    assert "CURRENT SQL" in prompt


def test_correction_prompt_contains_execution_error():
    prompt = build_correction_prompt(
        question="List all employees",
        current_sql="SELECT name FROM employees;",
        execution_error="no such column: name",
        error_type="missing_column",
        schema_context_text="COLUMN: employees.employee_name",
        reference_result_text="",
    )
    assert "no such column: name" in prompt
    assert "EXECUTION ERROR" in prompt
    assert "missing_column" in prompt


def test_correction_prompt_contains_retrieved_schema():
    prompt = build_correction_prompt(
        question="List all employees",
        current_sql="SELECT name FROM employees;",
        execution_error="no such column: name",
        error_type="missing_column",
        schema_context_text="COLUMN: employees.employee_name\nTYPE: TEXT",
        reference_result_text="",
    )
    assert "RETRIEVED SCHEMA" in prompt
    assert "employees.employee_name" in prompt


def test_correction_prompt_prohibits_invented_tables_columns():
    prompt = build_correction_prompt(
        question="List all employees",
        current_sql="SELECT name FROM employees;",
        execution_error="no such column: name",
        error_type="missing_column",
        schema_context_text="COLUMN: employees.employee_name",
        reference_result_text="",
    )
    assert "Do not invent tables or columns" in prompt


def test_correction_prompt_forbids_destructive_operations():
    prompt = build_correction_prompt(
        question="List all employees",
        current_sql="SELECT name FROM employees;",
        execution_error="no such column: name",
        error_type="missing_column",
        schema_context_text="COLUMN: employees.employee_name",
        reference_result_text="",
    )
    for op in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE"):
        assert op in prompt


def test_correction_prompt_result_mismatch_mode():
    prompt = build_correction_prompt(
        question="Count employees",
        current_sql="SELECT COUNT(*) FROM departments;",
        execution_error="",
        error_type="incorrect_result",
        schema_context_text="TABLE: employees\nCOLUMN: employees.employee_id",
        reference_result_text="Columns: employee_count\nRow count: 1\nSample rows:\n(500,)",
    )
    assert "RESULT MISMATCH" in prompt
    assert "incorrect result" in prompt.lower()
    assert "employee_count" in prompt


# ---------------------------------------------------------------------------
# 2. Correction context text from retrieval
# ---------------------------------------------------------------------------

def test_build_correction_context_text_from_retrieval(tmp_path):
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH),
        persist_dir=persist,
        embedding_dimensions=384,
        top_k=5,
        embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("average salary by department")
    context = build_correction_context_text(retrieval)
    assert "employees" in context.lower() or "departments" in context.lower()


# ---------------------------------------------------------------------------
# 3. SQLCorrector with mocked LLM
# ---------------------------------------------------------------------------

class MockOllama:
    """Mock LLM that returns pre-programmed SQL corrections."""
    
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0
    
    def generate(self, prompt, model=None, timeout=None):
        self.call_count += 1
        if self.call_count <= len(self.responses):
            return self.responses[self.call_count - 1], 100.0
        return "SELECT 1;", 100.0


def test_correction_loop_successful_first_pass(tmp_path):
    """SQL that executes correctly on first attempt should not trigger correction."""
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("List all employee names.")
    
    # LLM returns correct SQL on first try
    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        mock_gen.return_value = ("SELECT employee_name FROM employees;", 100.0)
        
        corrector = SQLCorrector(
            db_path=str(DB_PATH),
            model="qwen2.5-coder:1.5b",
            max_attempts=3,
        )
        result = corrector.correct(
            question="List all employee names.",
            category="SELECT",
            question_id="q01",
            reference_sql="SELECT employee_name FROM employees;",
            original_sql="SELECT employee_name FROM employees;",
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=True,
        )
    
    assert result.final_correct is True
    assert result.total_attempts == 1
    assert result.rescued is False
    assert result.harmed is False
    assert len(result.attempts) == 1


def test_correction_loop_syntax_error_fixed(tmp_path):
    """Syntax error on first attempt, corrected on second."""
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("List all employee names.")
    
    # The original SQL has a genuine syntax error. The mocked LLM fixes it
    # on its first (and only) correction call.
    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        mock_gen.side_effect = [
            ("SELECT employee_name FROM employees;", 100.0),  # corrected
        ]
        
        corrector = SQLCorrector(
            db_path=str(DB_PATH),
            model="qwen2.5-coder:1.5b",
            max_attempts=3,
        )
        result = corrector.correct(
            question="List all employee names.",
            category="SELECT",
            question_id="q01",
            reference_sql="SELECT employee_name FROM employees;",
            original_sql="SELECT employee_name FROM employees WHERE ",  # incomplete input
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=False,
        )
    
    assert result.final_correct is True
    assert result.total_attempts == 2
    assert result.rescued is True  # L7 wrong -> L8 correct
    assert len(result.attempts) == 2
    assert "syntax" in result.attempts[0].execution_error_type.lower() or "incomplete" in (result.attempts[0].execution_error_type or "").lower()


def test_correction_loop_missing_column_fixed(tmp_path):
    """Missing column error corrected by using retrieved schema."""
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("List all employee names.")
    
    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        mock_gen.side_effect = [
            ("SELECT employee_name FROM employees;", 100.0),  # corrected
        ]
        
        corrector = SQLCorrector(
            db_path=str(DB_PATH),
            model="qwen2.5-coder:1.5b",
            max_attempts=3,
        )
        result = corrector.correct(
            question="List all employee names.",
            category="SELECT",
            question_id="q01",
            reference_sql="SELECT employee_name FROM employees;",
            original_sql="SELECT name FROM employees;",
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=False,
        )
    
    assert result.final_correct is True
    assert result.total_attempts == 2
    assert result.rescued is True
    assert result.attempts[0].execution_error_type == "missing_column"


def test_correction_loop_missing_table_fixed(tmp_path):
    """Missing table error corrected."""
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("List all employee names.")
    
    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        mock_gen.side_effect = [
            ("SELECT employee_name FROM employees;", 100.0),  # corrected
        ]
        
        corrector = SQLCorrector(
            db_path=str(DB_PATH),
            model="qwen2.5-coder:1.5b",
            max_attempts=3,
        )
        result = corrector.correct(
            question="List all employee names.",
            category="SELECT",
            question_id="q01",
            reference_sql="SELECT employee_name FROM employees;",
            original_sql="SELECT employee_name FROM staff;",
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=False,
        )
    
    assert result.final_correct is True
    assert result.total_attempts == 2
    assert result.rescued is True
    assert result.attempts[0].execution_error_type == "missing_table"


def test_correction_loop_max_attempts_reached(tmp_path):
    """After max_attempts, loop stops even if not correct."""
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("List all employee names.")
    
    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        # Each correction returns a DIFFERENT but still-wrong SQL so the loop
        # reaches the retry limit (never the same statement twice, and never
        # equal to the original).
        mock_gen.side_effect = [
            ("SELECT employee_name FROM ghost;", 100.0),   # missing table
            ("SELECT employee_name FROM staff;", 100.0),   # missing table
            ("SELECT full_name FROM employees;", 100.0),   # missing column
        ]
        
        corrector = SQLCorrector(
            db_path=str(DB_PATH),
            model="qwen2.5-coder:1.5b",
            max_attempts=3,
        )
        result = corrector.correct(
            question="List all employee names.",
            category="SELECT",
            question_id="q01",
            reference_sql="SELECT employee_name FROM employees;",
            original_sql="SELECT name FROM employees;",
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=False,
        )
    
    assert result.final_correct is False
    assert result.total_attempts == 3
    assert len(result.attempts) == 3
    assert result.rescued is False


def test_correction_loop_does_not_blindly_retry_same_sql(tmp_path):
    """If the model echoes the same SQL, the loop stops (no blind retry)."""
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("List all employee names.")
    
    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        # LLM returns the SAME (failing) SQL it was asked to fix
        mock_gen.return_value = ("SELECT name FROM employees;", 100.0)
        
        corrector = SQLCorrector(
            db_path=str(DB_PATH),
            model="qwen2.5-coder:1.5b",
            max_attempts=5,
        )
        result = corrector.correct(
            question="List all employee names.",
            category="SELECT",
            question_id="q01",
            reference_sql="SELECT employee_name FROM employees;",
            original_sql="SELECT name FROM employees;",
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=False,
        )
    
    assert result.final_correct is False
    # The echoed statement equals the original, which is already seen, so the
    # loop stops immediately after the first attempt with no_progress.
    assert len(result.attempts) == 1
    assert result.attempts[0].execution_error_type == "no_progress"
    assert result.total_attempts == 1


def test_correction_loop_unsafe_sql_rejected(tmp_path):
    """LLM returns unsafe SQL (INSERT) -> validation_error -> loop stops."""
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("List all employee names.")
    
    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        mock_gen.side_effect = [
            ("INSERT INTO employees (employee_name) VALUES ('test');", 100.0),
        ]
        
        corrector = SQLCorrector(
            db_path=str(DB_PATH),
            model="qwen2.5-coder:1.5b",
            max_attempts=3,
        )
        result = corrector.correct(
            question="List all employee names.",
            category="SELECT",
            question_id="q01",
            reference_sql="SELECT employee_name FROM employees;",
            original_sql="SELECT name FROM employees;",
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=False,
        )
    
    assert result.final_correct is False
    assert len(result.attempts) == 1
    assert result.attempts[0].execution_error_type == "validation_error"


def test_correction_loop_llm_error_stops(tmp_path):
    """LLM connection error stops the loop."""
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("List all employee names.")
    
    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        from backend.llm.ollama_client import OllamaError
        mock_gen.side_effect = OllamaError("connection refused")
        
        corrector = SQLCorrector(
            db_path=str(DB_PATH),
            model="qwen2.5-coder:1.5b",
            max_attempts=3,
        )
        result = corrector.correct(
            question="List all employee names.",
            category="SELECT",
            question_id="q01",
            reference_sql="SELECT employee_name FROM employees;",
            original_sql="SELECT name FROM employees;",
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=False,
        )
    
    assert result.final_correct is False
    assert len(result.attempts) == 1
    assert result.attempts[0].execution_error_type == "llm_error"


def test_correction_preserves_original_sql(tmp_path):
    """Original SQL is preserved in CorrectionResult."""
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("List all employee names.")
    
    original = "SELECT name FROM employees;"
    
    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        mock_gen.side_effect = [
            ("SELECT employee_name FROM employees;", 100.0),
        ]
        
        corrector = SQLCorrector(
            db_path=str(DB_PATH),
            model="qwen2.5-coder:1.5b",
            max_attempts=3,
        )
        result = corrector.correct(
            question="List all employee names.",
            category="SELECT",
            question_id="q01",
            reference_sql="SELECT employee_name FROM employees;",
            original_sql=original,
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=False,
        )
    
    assert result.original_sql == original
    assert result.attempts[0].sql == original


def test_correction_records_all_attempts_deterministically(tmp_path):
    """Each attempt records sql, prompt, raw_response, execution_result."""
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("List all employee names.")
    
    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        mock_gen.side_effect = [
            ("SELECT employee_name FROM employees;", 100.0),
        ]
        
        corrector = SQLCorrector(
            db_path=str(DB_PATH),
            model="qwen2.5-coder:1.5b",
            max_attempts=3,
        )
        result = corrector.correct(
            question="List all employee names.",
            category="SELECT",
            question_id="q01",
            reference_sql="SELECT employee_name FROM employees;",
            original_sql="SELECT name FROM employees;",
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=False,
        )
    
    assert len(result.attempts) == 2
    for i, attempt in enumerate(result.attempts):
        assert attempt.attempt_number == i + 1
        assert attempt.sql
        assert attempt.execution_result is not None
        assert attempt.execution_time_ms >= 0
        if attempt.is_correct:
            # final successful attempt makes no further LLM call
            assert attempt.prompt == ""
            assert attempt.raw_response == ""
        else:
            assert attempt.prompt  # prompt was built for the failing attempt
            assert attempt.raw_response  # LLM response recorded


def test_correction_result_mismatch_mode(tmp_path):
    """When SQL executes but produces wrong result, correction prompt includes reference."""
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("Count employees.")
    
    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        # First response is the corrected SQL (mounted after attempt 1 fails).
        mock_gen.side_effect = [
            ("SELECT COUNT(*) AS employee_count FROM employees;", 100.0),
        ]
        
        corrector = SQLCorrector(
            db_path=str(DB_PATH),
            model="qwen2.5-coder:1.5b",
            max_attempts=3,
        )
        result = corrector.correct(
            question="Count employees.",
            category="aggregate",
            question_id="q41",
            reference_sql="SELECT COUNT(*) AS employee_count FROM employees;",
            original_sql="SELECT COUNT(*) FROM departments;",
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=False,
        )
    
    assert result.final_correct is True
    assert result.total_attempts == 2
    assert result.rescued is True
    # First attempt executes successfully but produces the wrong result
    assert result.attempts[0].execution_result.success is True
    assert result.attempts[0].is_correct is False


def test_correction_does_not_harm_correct_l7_sql(tmp_path):
    """A correct L7 SQL is left untouched: loop stops at attempt 1, no LLM call.

    This encodes the experimental rule that L8 must never modify a correct
    first-pass SQL (the loop breaks immediately when execution is correct).
    """
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("List all employee names.")

    original = "SELECT employee_name FROM employees;"

    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        mock_gen.return_value = ("SELECT name FROM employees;", 100.0)  # never used

        corrector = SQLCorrector(
            db_path=str(DB_PATH),
            model="qwen2.5-coder:1.5b",
            max_attempts=3,
        )
        result = corrector.correct(
            question="List all employee names.",
            category="SELECT",
            question_id="q01",
            reference_sql="SELECT employee_name FROM employees;",
            original_sql=original,  # L7 correct
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=True,
        )

    assert result.final_correct is True
    assert result.final_sql == original
    assert result.total_attempts == 1
    assert result.harmed is False
    assert result.rescued is False
    mock_gen.assert_not_called()  # no correction attempt mounted


def test_correction_works_on_arbitrary_schema(tmp_path):
    """Correction loop works with an independent temporary database."""
    db = make_temp_db(tmp_path)
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(db), persist_dir=persist, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever.build_index()
    retrieval = retriever.retrieve("List all authors.")
    
    with patch("backend.correction.sql_corrector.generate") as mock_gen:
        mock_gen.side_effect = [
            ("SELECT author_name FROM authors;", 100.0),  # corrected
        ]
        
        corrector = SQLCorrector(
            db_path=str(db),
            model="qwen2.5-coder:1.5b",
            max_attempts=3,
        )
        result = corrector.correct(
            question="List all authors.",
            category="SELECT",
            question_id="t01",
            reference_sql="SELECT author_name FROM authors;",
            original_sql="SELECT author_name FROM author;",
            retrieval=retrieval,
            schema_context_text=build_correction_context_text(retrieval),
            is_l7_correct=False,
        )
    
    assert result.final_correct is True
    assert result.total_attempts == 2
    assert result.rescued is True


# ---------------------------------------------------------------------------
# 4. L4 executor unchanged
# ---------------------------------------------------------------------------

def test_l4_executor_still_works_and_rejects_writes():
    """The exact L4 executor is used, unchanged."""
    result = execute_sql("SELECT department_name FROM departments;", str(DB_PATH))
    assert result.success
    
    result = execute_sql("DELETE FROM departments;", str(DB_PATH))
    assert not result.success
    assert result.error_type == "validation_error"


# ---------------------------------------------------------------------------
# 5. All previous tests still pass (sanity check)
# ---------------------------------------------------------------------------

def test_previous_levels_import():
    """All L1-L7 imports still work."""
    from backend.database import executor, schema_inspector
    from backend.evaluation import evaluator, metrics
    from backend.llm import ollama_client, sql_generator
    from backend.retrieval import schema_retriever, embeddings, chroma_store, schema_documents
    from backend.phonetics import normalizer, algorithms, vocabulary
    from backend.correction import correction_prompt, sql_corrector
    assert True