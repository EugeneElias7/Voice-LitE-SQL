"""Voice-LitE-SQL -- Level 3: prompt construction from L2 schema output.

The schema is rendered from :class:`backend.database.schema_inspector.Schema`
objects -- nothing about the enterprise database is hardcoded here.
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


def format_schema(schema):
    """Render a Schema into a compact textual description for the prompt."""
    lines = []
    for table in schema.tables:
        if table.primary_keys:
            lines.append(
                f"TABLE {table.name}  (PRIMARY KEY: {', '.join(table.primary_keys)})"
            )
        else:
            lines.append(f"TABLE {table.name}  (no primary key)")
        for column in table.columns:
            parts = [column.name, column.data_type or ""]
            if column.not_null:
                parts.append("NOT NULL")
            if column.primary_key_position:
                parts.append(f"(PK part {column.primary_key_position})")
            lines.append("  - " + " ".join(parts))
        for fk in table.foreign_keys:
            lines.append(
                f"  FK: {fk.source_column} -> {fk.target_table}({fk.target_column})"
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def build_sql_prompt(question, schema):
    """Build the SQL generation prompt for the local Qwen model."""
    schema_text = format_schema(schema)
    forbidden = ", ".join(FORBIDDEN_OPERATIONS)
    return f"""You are a SQLite SQL generation assistant.

Generate a single SQLite query that answers the user's question.

Rules:
- Return ONLY the SQL statement, with no explanation.
- Use ONLY tables and columns listed in the schema below. Never invent tables or columns.
- Use SELECT (or WITH) only. The following operations are strictly forbidden: {forbidden}.
- Prefer simple, correct queries. Use JOIN only when the schema relationships require it.
- IMPORTANT: When the question asks for counts from MULTIPLE INDEPENDENT tables (e.g. "how many X and how many Y"), do NOT join those tables. Use separate subqueries or UNION ALL instead:
  SELECT (SELECT COUNT(*) FROM TableA) AS count_a, (SELECT COUNT(*) FROM TableB) AS count_b
  OR
  SELECT 'TableA' AS type, COUNT(*) FROM TableA UNION ALL SELECT 'TableB', COUNT(*) FROM TableB

DATABASE SCHEMA
{schema_text}

QUESTION
{question}

SQL:"""
