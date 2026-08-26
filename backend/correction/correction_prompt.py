"""Voice-LitE-SQL -- Level 8: execution-guided SQL self-correction prompt.

Builds a correction prompt that provides the LLM with:
- the original question
- the current (failing) SQL
- the SQLite execution error or incorrect result signal
- the relevant retrieved schema (from L7)
- explicit instructions to fix and return corrected SQL only
"""

FORBIDDEN_OPERATIONS = (
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


def build_correction_prompt(
    question: str,
    current_sql: str,
    execution_error: str,
    error_type: str,
    schema_context_text: str,
    reference_result_text: str = "",
) -> str:
    """Build the L8 correction prompt.

    Parameters
    ----------
    question:
        The original natural-language question.
    current_sql:
        The SQL that was just executed and failed or produced wrong result.
    execution_error:
        The error message from SQLite execution (empty if SQL executed but
        produced wrong result).
    error_type:
        One of: 'syntax_error', 'missing_column', 'missing_table',
        'sqlite_error', 'incorrect_result', or 'generation_error'.
    schema_context_text:
        The retrieved schema context from L7 (tables, columns, relationships).
    reference_result_text:
        Optional human-readable description of the expected result. Only
        provided in evaluation mode when a reference is available.
        Never used in production.
    """
    forbidden = ", ".join(FORBIDDEN_OPERATIONS)

    error_section = ""
    if execution_error:
        error_section = f"""EXECUTION ERROR
Type: {error_type}
Message: {execution_error}

The above SQL failed to execute. Fix the error and return corrected SQL.
"""
    elif reference_result_text:
        error_section = f"""RESULT MISMATCH
The SQL executed successfully but produced an incorrect result.

Expected result (for evaluation only):
{reference_result_text}

Fix the SQL logic to produce the correct result.
"""

    return f"""You are a SQLite SQL correction assistant.

The previous SQL was incorrect. Fix it.

Rules:
- Return ONLY the corrected SQL statement, with no explanation.
- Use only the provided schema. Do not invent tables or columns.
- Use SELECT (or WITH) only. The following operations are strictly forbidden: {forbidden}.
- Use JOIN only when the schema relationships below require it.
- You may only reference the foreign key relationships listed below.
- Do not repeat the same mistake.

RETRIEVED SCHEMA
{schema_context_text}

ORIGINAL QUESTION
{question}

CURRENT SQL
{current_sql}

{error_section}SQL:"""