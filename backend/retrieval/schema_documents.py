"""Voice-LitE-SQL -- Level 7: database-driven schema documents.

Generates searchable schema documents from the L2 SchemaInspector output of
any SQLite database. The documents are grouped into three kinds:

- table-level documents: the table name plus its columns and their types
- column-level documents: one document per column (table, column, type, PK,
  FK)
- relationship documents: one document per foreign key
  (source table/column -> target table/column)

Everything here is driven by the L2 inspector output, never by hardcoded
enterprise.db schema and never by ``backend.database.models``.
"""

from dataclasses import dataclass, field

from backend.database.schema_inspector import inspect_database

TABLE_DOC = "table"
COLUMN_DOC = "column"
RELATIONSHIP_DOC = "relationship"

DOC_ID_SEP = "."


@dataclass(frozen=True)
class SchemaDocument:
    """A single searchable schema document.

    Attributes
    ----------
    doc_id:
        deterministic document ID (e.g. ``col:employees.salary``).
    doc_type:
        one of ``table``, ``column``, ``relationship``.
    text:
        the searchable text sent to the embedder.
    table:
        the table this document refers to ('' when not applicable).
    column:
        the column this document refers to ('' when not applicable).
    fk_source_table / fk_source_column / fk_target_table / fk_target_column:
        foreign-key endpoints for relationship documents ('' otherwise).
    """

    doc_id: str
    doc_type: str
    text: str
    table: str = ""
    column: str = ""
    fk_source_table: str = ""
    fk_source_column: str = ""
    fk_target_table: str = ""
    fk_target_column: str = ""

    def to_dict(self):
        return {
            "doc_id": self.doc_id,
            "doc_type": self.doc_type,
            "text": self.text,
            "table": self.table,
            "column": self.column,
            "fk_source_table": self.fk_source_table,
            "fk_source_column": self.fk_source_column,
            "fk_target_table": self.fk_target_table,
            "fk_target_column": self.fk_target_column,
        }


# ---------------------------------------------------------------------------
# Text builders
# ---------------------------------------------------------------------------
def _column_line(table, column):
    """One column entry for a table-level document, e.g.::

        salary REAL

    Primary keys and foreign keys are annotated so the table document is
    self-contained for the LLM.
    """
    parts = [column.name, column.data_type or ""]
    if column.primary_key_position:
        parts.append("PRIMARY KEY")
    fk = next(
        (
            fk
            for fk in table.foreign_keys
            if fk.source_column == column.name
        ),
        None,
    )
    if fk is not None:
        parts.append(
            f"FOREIGN KEY -> {fk.target_table}.{fk.target_column}"
        )
    return " ".join(part for part in parts if part)


def _table_document_text(table):
    """Text for one table-level document."""
    lines = [f"TABLE: {table.name}", "COLUMNS:"]
    lines.extend(_column_line(table, column) for column in table.columns)
    return "\n".join(lines)


def _column_document_text(table, column):
    """Text for one column-level document."""
    lines = [
        f"COLUMN: {table.name}.{column.name}",
        f"TABLE: {table.name}",
        f"TYPE: {column.data_type or ''}",
    ]
    if column.primary_key_position:
        lines.append("PRIMARY KEY: yes")
    fk = next(
        (
            fk
            for fk in table.foreign_keys
            if fk.source_column == column.name
        ),
        None,
    )
    if fk is not None:
        lines.append(
            f"FOREIGN KEY: {fk.target_table}.{fk.target_column}"
        )
    return "\n".join(lines)


def _relationship_document_text(source_table, fk):
    """Text for one relationship (foreign key) document."""
    return (
        "RELATIONSHIP:\n"
        f"{source_table}.{fk.source_column}\n"
        f"-> {fk.target_table}.{fk.target_column}"
    )


# ---------------------------------------------------------------------------
# Document generation
# ---------------------------------------------------------------------------
def table_document_id(table_name):
    return f"{TABLE_DOC}:{table_name}"


def column_document_id(table_name, column_name):
    return f"{COLUMN_DOC}:{table_name}{DOC_ID_SEP}{column_name}"


def relationship_document_id(source_table, fk):
    return (
        f"{RELATIONSHIP_DOC}:{source_table}{DOC_ID_SEP}"
        f"{fk.source_column}->{fk.target_table}{DOC_ID_SEP}"
        f"{fk.target_column}"
    )


def generate_schema_documents(db_path):
    """Generate all schema documents for an arbitrary SQLite database.

    Returns a list of :class:`SchemaDocument`. The document order is
    deterministic: tables (sorted), then their columns, then their foreign
    keys -- exactly the order produced by the L2 inspector.

    Raises ``DatabaseError`` if the database is missing/invalid.
    """
    schema = inspect_database(db_path)
    documents = []

    for table in schema.tables:
        table_doc = SchemaDocument(
            doc_id=table_document_id(table.name),
            doc_type=TABLE_DOC,
            text=_table_document_text(table),
            table=table.name,
        )
        documents.append(table_doc)

        for column in table.columns:
            documents.append(
                SchemaDocument(
                    doc_id=column_document_id(table.name, column.name),
                    doc_type=COLUMN_DOC,
                    text=_column_document_text(table, column),
                    table=table.name,
                    column=column.name,
                )
            )

        for fk in table.foreign_keys:
            documents.append(
                SchemaDocument(
                    doc_id=relationship_document_id(table.name, fk),
                    doc_type=RELATIONSHIP_DOC,
                    text=_relationship_document_text(table.name, fk),
                    table=table.name,
                    column=fk.source_column,
                    fk_source_table=table.name,
                    fk_source_column=fk.source_column,
                    fk_target_table=fk.target_table,
                    fk_target_column=fk.target_column,
                )
            )

    return documents


def documents_by_id(documents):
    return {doc.doc_id: doc for doc in documents}