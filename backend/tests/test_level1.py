"""Voice-LitE-SQL -- Level 1 tests: Data Foundation."""

import json
import sqlite3
from pathlib import Path

import pytest

from backend.database.models import SEED, TABLES
from backend.database.seed import build_database, DEFAULT_DB_PATH, DEFAULT_SCHEMA_PATH

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = PROJECT_ROOT / "backend" / "datasets" / "custom"

EXPECTED_COUNTS = {
    "locations": 30,
    "departments": 15,
    "employees": 500,
    "customers": 1000,
    "products": 250,
    "sales": 5000,
    "orders": 2500,
}

QUESTION_DISTRIBUTION = {
    "SELECT": 10,
    "WHERE": 10,
    "JOIN": 10,
    "GROUP BY": 5,
    "ORDER BY": 5,
    "aggregate": 5,
    "complex": 5,
}

FORBIDDEN_KEYWORDS = (
    "DELETE", "DROP", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE",
    "PRAGMA", "ATTACH",
)


@pytest.fixture(scope="session", autouse=True)
def ensure_database():
    """Rebuild the database if it does not exist yet (e.g. fresh clone)."""
    if not DEFAULT_DB_PATH.exists():
        build_database(DEFAULT_DB_PATH, DEFAULT_SCHEMA_PATH)


def connect():
    return sqlite3.connect(str(DEFAULT_DB_PATH))


def schema_terms():
    terms = set(TABLES)
    for definition in TABLES.values():
        terms.update(definition["columns"])
    return terms


# -- database ---------------------------------------------------------------

def test_database_exists():
    assert DEFAULT_DB_PATH.exists()


def test_tables_and_columns():
    conn = connect()
    try:
        for table, definition in TABLES.items():
            actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert actual == set(definition["columns"]), f"columns mismatch in {table}"
    finally:
        conn.close()


def test_row_counts():
    conn = connect()
    try:
        for table, expected in EXPECTED_COUNTS.items():
            actual = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert actual == expected, f"{table} has {actual} rows, expected {expected}"
    finally:
        conn.close()


def test_foreign_key_integrity():
    conn = connect()
    try:
        for table, definition in TABLES.items():
            for column, ddl in definition["columns"].items():
                ref = ddl.partition("REFERENCES")[2].strip()
                if not ref:
                    continue
                ref_table, _, ref_cols = ref.partition("(")
                ref_column = ref_cols.rstrip(")").strip().split(",")[0].strip()
                orphans = conn.execute(
                    f"SELECT COUNT(*) FROM {table} t"
                    f" LEFT JOIN {ref_table} r ON t.{column} = r.{ref_column}"
                    f" WHERE t.{column} IS NOT NULL AND r.{ref_column} IS NULL"
                ).fetchone()[0]
                assert orphans == 0, (
                    f"orphan rows in {table}.{column} -> {ref_table}.{ref_column}"
                )
    finally:
        conn.close()


def test_seed_reproducible(tmp_path):
    db1 = tmp_path / "a" / "enterprise.db"
    db2 = tmp_path / "b" / "enterprise.db"
    build_database(db1, seed=SEED)
    build_database(db2, seed=SEED)
    assert db1.read_bytes() == db2.read_bytes()


# -- schema.json ------------------------------------------------------------

def test_schema_json():
    schema = json.loads(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert set(schema) == set(TABLES)
    for table, definition in TABLES.items():
        assert schema[table]["columns"] == list(definition["columns"])


# -- questions.json ---------------------------------------------------------

def test_questions_load():
    questions = json.loads((DATASET_DIR / "questions.json").read_text(encoding="utf-8"))
    assert len(questions) == 50
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids)), "duplicate question ids"
    for q in questions:
        assert {"id", "category", "question", "sql"} <= set(q)
        assert q["question"].strip()


def test_question_distribution():
    questions = json.loads((DATASET_DIR / "questions.json").read_text(encoding="utf-8"))
    actual = {}
    for q in questions:
        actual[q["category"]] = actual.get(q["category"], 0) + 1
    assert actual == QUESTION_DISTRIBUTION


def test_questions_execute():
    questions = json.loads((DATASET_DIR / "questions.json").read_text(encoding="utf-8"))
    conn = connect()
    try:
        for q in questions:
            sql = q["sql"].strip()
            head = sql.split()[0].upper() if sql else ""
            assert head == "SELECT", f"{q['id']} is not a SELECT statement"
            assert not any(kw in sql.upper() for kw in FORBIDDEN_KEYWORDS), (
                f"{q['id']} contains a forbidden keyword"
            )
            conn.execute(sql).fetchall()
    finally:
        conn.close()


# -- corrupted_queries.json -------------------------------------------------

def test_corrupted_queries():
    corrupted = json.loads(
        (DATASET_DIR / "corrupted_queries.json").read_text(encoding="utf-8")
    )
    assert len(corrupted) >= 20
    terms = schema_terms()
    for entry in corrupted:
        assert {"original", "corrupted", "target"} <= set(entry)
        assert entry["corrupted"] != entry["original"]
        target = entry["target"].lower()
        assert any(
            target in t.lower() or t.lower() in target for t in terms
        ), f"target '{entry['target']}' not in schema vocabulary"
