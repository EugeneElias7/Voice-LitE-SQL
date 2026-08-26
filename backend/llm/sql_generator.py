"""Voice-LitE-SQL -- Level 3: text-to-SQL baseline.

Pipeline: question -> L2 schema inspection -> prompt -> local Ollama
(qwen2.5-coder:1.5b) -> SQL extraction -> read-only validation.

Execution is NOT part of this level (that is Level 4).
"""

import re
from dataclasses import dataclass

from backend.database.connection import DatabaseError
from backend.database.schema_inspector import inspect_database
from backend.llm.ollama_client import (
    DEFAULT_HOST,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    OllamaError,
    generate,
)
from backend.llm.prompts import build_sql_prompt

READ_ONLY_PREFIXES = ("SELECT", "WITH")

FORBIDDEN_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "ATTACH",
    "DETACH",
    "PRAGMA",
    "REPLACE",
    "TRUNCATE",
    "VACUUM",
    "GRANT",
    "REVOKE",
)


@dataclass
class SQLGenerationResult:
    question: str
    generated_sql: str
    model_name: str
    raw_response: str
    success: bool
    error: str = None


def validate_read_only(sql):
    """Lightweight read-only check.

    NOT a complete security sandbox: Level 4 implements actual execution
    safety. This only catches obviously unsafe statements early.
    """
    if not sql or not sql.strip():
        raise ValueError("empty SQL")
    stripped = sql.strip()
    head = stripped.split(None, 1)[0].upper()
    if head not in READ_ONLY_PREFIXES:
        raise ValueError(f"SQL must start with SELECT or WITH, got '{head}'")
    upper = stripped.upper()
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper):
            raise ValueError(f"forbidden keyword: {keyword}")
    return sql


def extract_sql(response_text):
    """Robustly extract a SQL statement from a model response.

    Handles: plain SQL, ```sql ... ``` fences, surrounding explanatory
    text, and whitespace/newline variations.
    """
    if not response_text or not response_text.strip():
        raise ValueError("model returned an empty response")
    text = response_text.strip()
    fenced = re.search(r"```(?:sql|SQL)?\s*(.*?)```", text, re.DOTALL)
    sql = fenced.group(1).strip() if fenced else text
    match = re.search(r"(?:SELECT|WITH)\b", sql, re.IGNORECASE)
    if not match:
        raise ValueError("no SQL statement found in model response")
    sql = sql[match.start():]
    last_semicolon = sql.rfind(";")
    if last_semicolon != -1:
        sql = sql[:last_semicolon + 1]
    sql = sql.strip()
    if not sql:
        raise ValueError("no SQL statement found in model response")
    return sql


def generate_sql(question, db_path, model=DEFAULT_MODEL, host=DEFAULT_HOST, timeout=DEFAULT_TIMEOUT, validate=True):
    """Run the full text-to-SQL pipeline and return a structured result."""
    try:
        schema = inspect_database(db_path)
    except DatabaseError as exc:
        return SQLGenerationResult(
            question, None, model, "", False,
            f"schema inspection failed: {exc}",
        )

    prompt = build_sql_prompt(question, schema)
    try:
        raw_response, _ = generate(prompt, model=model, host=host, timeout=timeout)
    except OllamaError as exc:
        return SQLGenerationResult(
            question, None, model, "", False, f"ollama error: {exc}",
        )

    try:
        sql = extract_sql(raw_response)
        if validate:
            validate_read_only(sql)
    except ValueError as exc:
        return SQLGenerationResult(
            question, None, model, raw_response, False,
            f"sql extraction failed: {exc}",
        )

    return SQLGenerationResult(question, sql, model, raw_response, True, None)
