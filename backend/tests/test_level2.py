"""Voice-LitE-SQL -- Level 2 tests: connection abstraction + schema inspection."""

import sqlite3
from pathlib import Path

import pytest

from backend.database.connection import DatabaseConnection, DatabaseError
from backend.database.models import TABLES
from backend.database.schema_inspector import inspect_database

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "backend" / "data" / "enterprise.db"

EXPECTED_TABLES = set(TABLES)
EXPECTED_COLUMNS = {
    table: list(definition["columns"]) for table, definition in TABLES.items()
}
EXPECTED_PKS = {
    "locations": ("location_id",),
    "departments": ("department_id",),
    "employees": ("employee_id",),
    "customers": ("customer_id",),
    "products": ("product_id",),
    "sales": ("sale_id",),
    "orders": ("order_id",),
}
EXPECTED_FKS = {
    "departments": {"location_id": ("locations", "location_id")},
    "employees": {"department_id": ("departments", "department_id")},
    "sales": {
        "employee_id": ("employees", "employee_id"),
        "customer_id": ("customers", "customer_id"),
        "product_id": ("products", "product_id"),
    },
    "orders": {
        "customer_id": ("customers", "customer_id"),
        "product_id": ("products", "product_id"),
        "employee_id": ("employees", "employee_id"),
    },
}
EXPECTED_DATA_TYPES = {
    "employees": {
        "employee_id": "INTEGER",
        "employee_name": "TEXT",
        "department_id": "INTEGER",
        "salary": "REAL",
        "hire_date": "TEXT",
    },
    "products": {"price": "REAL"},
    "departments": {"budget": "REAL"},
    "orders": {"status": "TEXT"},
}


def inspect_enterprise():
    return inspect_database(DB_PATH)


def table_by_name(schema, name):
    return next(table for table in schema.tables if table.name == name)


# -- connection -------------------------------------------------------------

def test_connection_context_manager():
    with DatabaseConnection(DB_PATH) as db:
        assert db.connection is not None
        assert db.execute("SELECT 1").fetchone()[0] == 1
    assert db.connection is None


def test_connection_foreign_keys_enforced():
    with DatabaseConnection(DB_PATH) as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_connection_invalid_path(tmp_path):
    with pytest.raises(DatabaseError, match="not found"):
        DatabaseConnection(tmp_path / "missing.db").connect()


# -- enterprise.db inspection ------------------------------------------------

def test_enterprise_db_inspectable():
    schema = inspect_enterprise()
    assert len(schema.tables) == 7


def test_tables_discovered():
    schema = inspect_enterprise()
    assert {table.name for table in schema.tables} == EXPECTED_TABLES


def test_columns_discovered():
    schema = inspect_enterprise()
    for name, columns in EXPECTED_COLUMNS.items():
        table = table_by_name(schema, name)
        assert [column.name for column in table.columns] == columns


def test_data_types_discovered():
    schema = inspect_enterprise()
    for table_name, type_map in EXPECTED_DATA_TYPES.items():
        table = table_by_name(schema, table_name)
        actual = {column.name: column.data_type for column in table.columns}
        for column_name, data_type in type_map.items():
            assert actual[column_name] == data_type


def test_primary_keys_discovered():
    schema = inspect_enterprise()
    for table in schema.tables:
        assert table.primary_keys == EXPECTED_PKS[table.name]
        for column in table.columns:
            if column.name == EXPECTED_PKS[table.name][0]:
                assert column.primary_key_position == 1


def test_foreign_keys_discovered():
    schema = inspect_enterprise()
    for table in schema.tables:
        if table.name in EXPECTED_FKS:
            assert len(table.foreign_keys) == len(EXPECTED_FKS[table.name])
        else:
            assert len(table.foreign_keys) == 0


def test_fk_relationships_and_sequence():
    schema = inspect_enterprise()
    for table_name, expected in EXPECTED_FKS.items():
        table = table_by_name(schema, table_name)
        actual = {
            fk.source_column: (fk.target_table, fk.target_column)
            for fk in table.foreign_keys
        }
        assert actual == expected
        assert sorted(fk.sequence for fk in table.foreign_keys) == [0] * len(expected)


def test_inspection_deterministic():
    first = inspect_enterprise().to_dict()
    second = inspect_enterprise().to_dict()
    assert first == second


# -- database-driven discovery (not based on models.py) ----------------------

def test_temp_database_not_models(tmp_path):
    db = tmp_path / "library.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
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
        CREATE TABLE empty_shelf (
            shelf_id INTEGER PRIMARY KEY,
            label    TEXT
        );
        """
    )
    conn.commit()
    conn.close()

    schema = inspect_database(db)
    assert [table.name for table in schema.tables] == [
        "authors",
        "books",
        "empty_shelf",
    ]

    authors = table_by_name(schema, "authors")
    assert authors.primary_keys == ("author_id",)
    assert {
        column.name: (column.data_type, column.not_null)
        for column in authors.columns
    } == {
        "author_id": ("INTEGER", False),
        "author_name": ("TEXT", True),
        "birth_year": ("INTEGER", False),
    }

    books = table_by_name(schema, "books")
    assert books.primary_keys == ("book_id",)
    assert len(books.foreign_keys) == 1
    fk = books.foreign_keys[0]
    assert (fk.source_column, fk.target_table, fk.target_column, fk.sequence) == (
        "author_id",
        "authors",
        "author_id",
        0,
    )
    pages = next(c for c in books.columns if c.name == "pages")
    assert pages.default_value == "0"

    empty_shelf = table_by_name(schema, "empty_shelf")
    assert [c.name for c in empty_shelf.columns] == ["shelf_id", "label"]
    assert empty_shelf.foreign_keys == ()


def test_empty_database(tmp_path):
    db = tmp_path / "empty.db"
    sqlite3.connect(str(db)).close()
    schema = inspect_database(db)
    assert schema.tables == ()


def test_invalid_database_file(tmp_path):
    bad = tmp_path / "not_a_db.txt"
    bad.write_text("this is definitely not a sqlite database", encoding="utf-8")
    with pytest.raises(DatabaseError, match="not a valid SQLite database"):
        inspect_database(bad)
