"""Voice-LitE-SQL -- Level 2: automatic schema inspection.

Discovers tables, columns, data types, primary keys and foreign keys of any
SQLite database, driven entirely by the database itself (no hardcoded table
or column definitions).

CLI usage:

    python -m backend.database.schema_inspector <database_path>
"""

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from backend.database.connection import DatabaseConnection, DatabaseError


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Column:
    name: str
    data_type: str
    not_null: bool
    default_value: object
    primary_key_position: int


@dataclass(frozen=True)
class ForeignKey:
    source_column: str
    target_table: str
    target_column: str
    sequence: int


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: tuple
    primary_keys: tuple
    foreign_keys: tuple

    def to_dict(self):
        return {
            "name": self.name,
            "columns": [
                {
                    "name": column.name,
                    "data_type": column.data_type,
                    "not_null": column.not_null,
                    "default_value": column.default_value,
                    "primary_key_position": column.primary_key_position,
                }
                for column in self.columns
            ],
            "primary_keys": list(self.primary_keys),
            "foreign_keys": [
                {
                    "source_column": fk.source_column,
                    "target_table": fk.target_table,
                    "target_column": fk.target_column,
                    "sequence": fk.sequence,
                }
                for fk in self.foreign_keys
            ],
        }


@dataclass(frozen=True)
class Schema:
    tables: tuple = ()

    def to_dict(self):
        return {"tables": [table.to_dict() for table in self.tables]}


# ---------------------------------------------------------------------------
# Inspection primitives
# ---------------------------------------------------------------------------
def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _user_table_names(cursor):
    cursor.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name"
    )
    return [row[0] for row in cursor.fetchall()]


def _inspect_table(cursor, table_name):
    cursor.execute(f"PRAGMA table_info({_quote(table_name)})")
    columns = []
    primary_key_positions = []
    for row in cursor.fetchall():
        _, name, data_type, not_null, default_value, pk_position = row
        columns.append(
            Column(
                name=name,
                data_type=data_type if data_type else None,
                not_null=bool(not_null),
                default_value=default_value,
                primary_key_position=pk_position if pk_position else 0,
            )
        )
        if pk_position:
            primary_key_positions.append((pk_position, name))
    primary_keys = tuple(name for _, name in sorted(primary_key_positions))

    cursor.execute(f"PRAGMA foreign_key_list({_quote(table_name)})")
    grouped = {}
    for row in cursor.fetchall():
        fk_id, sequence, target_table, source_column, target_column = row[:5]
        grouped.setdefault(fk_id, []).append(
            (sequence, source_column, target_table, target_column)
        )
    foreign_keys = []
    for fk_id in sorted(grouped):
        for sequence, source_column, target_table, target_column in sorted(grouped[fk_id]):
            if target_column is None:
                target_column = _resolve_implicit_target(cursor, target_table, sequence)
            foreign_keys.append(
                ForeignKey(
                    source_column=source_column,
                    target_table=target_table,
                    target_column=target_column,
                    sequence=sequence,
                )
            )
    return TableSchema(
        name=table_name,
        columns=tuple(columns),
        primary_keys=primary_keys,
        foreign_keys=tuple(foreign_keys),
    )


def _resolve_implicit_target(cursor, target_table, sequence):
    """SQLite leaves the target column empty when an FK references a PK."""
    cursor.execute(f"PRAGMA table_info({_quote(target_table)})")
    pk_columns = sorted((row[5], row[1]) for row in cursor.fetchall() if row[5])
    if not pk_columns:
        return None
    if sequence < len(pk_columns):
        return pk_columns[sequence][1]
    return pk_columns[0][1]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def inspect_database(db_path):
    """Inspect any SQLite database and return a normalized Schema.

    Raises :class:`DatabaseError` for missing files, non-files, and files
    that are not valid SQLite databases.
    """
    path = Path(db_path)
    with DatabaseConnection(path) as db:
        cursor = db.cursor()
        try:
            table_names = _user_table_names(cursor)
            tables = tuple(_inspect_table(cursor, name) for name in table_names)
        except sqlite3.DatabaseError as exc:
            raise DatabaseError(
                f"'{path}' is not a valid SQLite database: {exc}"
            ) from exc
    return Schema(tables=tables)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
DEFAULT_DB_PATH = (
    Path(__file__).resolve().parents[2] / "backend" / "data" / "enterprise.db"
)


def format_schema(schema, db_path):
    lines = [
        "DATABASE SCHEMA",
        "=" * 60,
        f"Database : {db_path}",
        f"Tables   : {len(schema.tables)}",
        "",
    ]
    for table in schema.tables:
        lines.append(f"Table: {table.name}")
        lines.append("  Columns:")
        for column in table.columns:
            pk = (
                f"  PK({column.primary_key_position})"
                if column.primary_key_position
                else ""
            )
            nn = "  NOT NULL" if column.not_null else ""
            lines.append(
                f"    - {column.name:<20} {column.data_type or 'N/A':<10}{pk}{nn}"
            )
        if table.primary_keys:
            lines.append(
                f"  Primary key : ({', '.join(table.primary_keys)})"
            )
        else:
            lines.append("  Primary key : none")
        if table.foreign_keys:
            lines.append("  Foreign keys:")
            for fk in table.foreign_keys:
                lines.append(
                    f"    - {fk.source_column} -> {fk.target_table}"
                    f"({fk.target_column})  [seq {fk.sequence}]"
                )
        else:
            lines.append("  Foreign keys: none")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    db_path = Path(argv[0]) if argv else DEFAULT_DB_PATH
    try:
        schema = inspect_database(db_path)
    except DatabaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(format_schema(schema, db_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
