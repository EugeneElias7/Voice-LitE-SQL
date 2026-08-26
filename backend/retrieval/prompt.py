"""Voice-LitE-SQL -- Level 7: schema-grounded prompt built from RETRIEVED schema.

Unlike the L4 prompt (which feeds the LLM the complete inspector output),
the L7 prompt feeds ONLY the retrieved schema context plus the relevant
foreign-key relationships. It keeps the SQLite / read-only / no-invention
rules that the whole pipeline relies on.
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


def build_l7_prompt(question, schema_context_text):
    """Build the L7 SQL generation prompt.

    ``schema_context_text`` must contain ONLY the retrieved/relevant schema
    (tables, columns, relationships) resolved for ``question``.
    """
    forbidden = ", ".join(FORBIDDEN_OPERATIONS)
    return f"""You are a SQLite SQL generation assistant.

Generate a single SQLite query that answers the user's question.

Rules:
- Return ONLY the SQL statement, with no explanation.
- Use only the provided schema. Do not invent tables or columns.
- Use SELECT (or WITH) only. The following operations are strictly forbidden: {forbidden}.
- Use JOIN only when the schema relationships below require it.
- You may only reference the foreign key relationships listed below.

RETRIEVED SCHEMA
{schema_context_text}

QUESTION
{question}

SQL:"""