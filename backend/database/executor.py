"""Voice-LitE-SQL -- Level 4: read-only SQL execution.

Executes only read-only SQL against a SQLite database using a genuinely
read-only connection (``mode=ro`` URI). Destructive/write statements and
multiple statements are rejected before any execution attempt.

The database is never modified by this module.
"""

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

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
    "REPLACE",
    "PRAGMA",
    "VACUUM",
    "GRANT",
    "REVOKE",
)


@dataclass
class ExecutionResult:
    success: bool
    columns: list = None
    rows: list = None
    row_count: int = 0
    execution_time_ms: float = 0.0
    error: str = None
    error_type: str = None


def _strip_literals_and_comments(sql):
    """Replace string literals and comments with neutral whitespace.

    Enables keyword/semicolon scanning without false positives inside
    quoted text (e.g. WHERE name = 'DELETE').
    """
    out = []
    i, n = 0, len(sql)
    while i < n:
        char = sql[i]
        if char == "'":
            out.append("'x'")
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
        elif char == "-" and i + 1 < n and sql[i + 1] == "-":
            out.append("  ")
            i += 2
            while i < n and sql[i] != "\n":
                out.append(" ")
                i += 1
        elif char == "/" and i + 1 < n and sql[i + 1] == "*":
            out.append("  ")
            i += 2
            while i < n - 1 and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i = min(i + 2, n)
        else:
            out.append(char)
            i += 1
    return "".join(out)


def _validation_error(sql):
    """Return an error message if the SQL is not safe read-only SQL, else None."""
    sql = (sql or "").strip()
    if not sql:
        return "empty SQL"
    clean = _strip_literals_and_comments(sql).strip()
    if clean.endswith(";"):
        clean = clean[:-1].strip()
    if ";" in clean:
        return "multiple SQL statements are not allowed"
    head = clean.split(None, 1)[0].upper() if clean else ""
    if head not in READ_ONLY_PREFIXES:
        return f"SQL must start with SELECT or WITH, got '{head}'"
    upper = clean.upper()
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper):
            return f"forbidden keyword: {keyword}"
    return None


def _classify_error(message):
    lowered = (message or "").lower()
    if "no such column" in lowered:
        return "missing_column"
    if "no such table" in lowered:
        return "missing_table"
    if "syntax error" in lowered or "incomplete input" in lowered:
        return "syntax_error"
    return "sqlite_error"


def execute_sql(sql, db_path):
    """Execute read-only SQL and return a structured ExecutionResult.

    Never modifies the database. All failures return controlled results.
    """
    sql = (sql or "").strip()
    message = _validation_error(sql)
    if message:
        return ExecutionResult(
            success=False,
            error=message,
            error_type="validation_error",
        )

    path = Path(db_path).resolve()
    if not path.exists():
        return ExecutionResult(
            success=False,
            error=f"database file not found: {path}",
            error_type="database_error",
        )

    uri = path.as_uri() + "?mode=ro"
    started = time.perf_counter()
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.execute("PRAGMA query_only = ON")
            cursor = conn.execute(sql)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            success, error, error_type = True, None, None
        finally:
            conn.close()
    except sqlite3.Error as exc:
        columns, rows = None, None
        success, error = False, str(exc)
        error_type = _classify_error(str(exc))
    elapsed = (time.perf_counter() - started) * 1000.0

    return ExecutionResult(
        success=success,
        columns=columns,
        rows=rows,
        row_count=len(rows) if rows else 0,
        execution_time_ms=round(elapsed, 3),
        error=error,
        error_type=error_type,
    )
