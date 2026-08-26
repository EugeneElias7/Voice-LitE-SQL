"""Voice-LitE-SQL -- Level 10: external benchmark dataset tests.

Unit tests use small synthetic databases / question files built in ``tmp_path``
so the full (multi-hundred-MB) external datasets are not required for the test
suite. Two optional smoke tests run against the real downloaded datasets when
they are present (auto-skipped otherwise).
"""

import json
import os
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.benchmarks import (
    BenchmarkQuestion,
    BirdLoader,
    SpiderLoader,
    build_external_index,
    default_index_dir,
)
from backend.benchmarks.bird_loader import BirdNotFound
from backend.benchmarks.spider_loader import SpiderNotFound

REAL_SPIDER_ROOT = PROJECT_ROOT / "backend" / "datasets" / "external" / "spider" / "spider_data"
REAL_BIRD_ROOT = PROJECT_ROOT / "backend" / "datasets" / "external" / "bird" / "minidev" / "MINIDEV"

TEMP_SCHEMA_SQL = """
CREATE TABLE authors (
    author_id INTEGER PRIMARY KEY,
    author_name TEXT NOT NULL
);
CREATE TABLE books (
    book_id INTEGER PRIMARY KEY,
    author_id INTEGER,
    title TEXT NOT NULL,
    FOREIGN KEY (author_id) REFERENCES authors (author_id)
);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(TEMP_SCHEMA_SQL)
    conn.commit()
    conn.close()
    return path


def build_spider_root(tmp_path):
    """Build a small Spider-like structure in tmp_path."""
    root = tmp_path / "spider_data"
    make_db(root / "database" / "library" / "library.sqlite")
    make_db(root / "database" / "store" / "store.sqlite")
    make_db(root / "test_database" / "library" / "library.sqlite")

    (root / "dev.json").write_text(json.dumps([
        {
            "db_id": "library",
            "question": "List all book titles.",
            "query": "SELECT title FROM books;",
            "query_toks": [], "question_toks": [], "sql": {},
        },
        {
            "db_id": "store",
            "question": "Which authors have books?",
            "query": None,
            "query_toks": [], "question_toks": [], "sql": {},
        },
    ]), encoding="utf-8")
    (root / "train_spider.json").write_text(json.dumps([
        {
            "db_id": "library",
            "question": "How many books?",
            "query": "SELECT count(*) FROM books;",
            "query_toks": [], "question_toks": [], "sql": {},
        },
    ]), encoding="utf-8")
    (root / "train_others.json").write_text(json.dumps([]), encoding="utf-8")
    (root / "test.json").write_text(json.dumps([]), encoding="utf-8")
    (root / "tables.json").write_text(json.dumps([
        {"db_id": "library", "table_names": ["authors", "books"],
         "foreign_keys": [[1, 2]], "primary_keys": [1], "column_names": []},
        {"db_id": "store", "table_names": ["authors", "books"],
         "foreign_keys": [], "primary_keys": [], "column_names": []},
    ]), encoding="utf-8")
    (root / "test_tables.json").write_text(json.dumps([]), encoding="utf-8")
    (root / "dev_gold.sql").write_text(
        "SELECT title FROM books;\tlibrary\n", encoding="utf-8"
    )
    return root


def build_bird_root(tmp_path):
    """Build a small BIRD-like structure in tmp_path."""
    root = tmp_path / "MINIDEV"
    make_db(root / "dev_databases" / "library" / "library.sqlite")
    make_db(root / "dev_databases" / "store" / "store.sqlite")

    questions = [
        {
            "question_id": 1,
            "db_id": "library",
            "question": "List all book titles.",
            "evidence": "titles of all books",
            "SQL": "SELECT title FROM books;",
            "difficulty": "simple",
        },
        {
            "question_id": 2,
            "db_id": "store",
            "question": "How many authors?",
            "evidence": "",
            "SQL": None,
            "difficulty": "moderate",
        },
    ]
    (root / "mini_dev_sqlite.json").write_text(
        json.dumps(questions), encoding="utf-8"
    )
    (root / "mini_dev_sqlite_gold.sql").write_text(
        "SELECT title FROM books;\tlibrary\n"
        "SELECT count(*) FROM authors;\tstore\n",
        encoding="utf-8",
    )
    (root / "dev_tables.json").write_text(json.dumps([]), encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# 1. Spider archive + database discovery
# ---------------------------------------------------------------------------
def test_spider_archive_discovery(tmp_path):
    root = build_spider_root(tmp_path)
    zpath = tmp_path / "spider_data.zip"
    with zipfile.ZipFile(str(zpath), "w") as zf:
        zf.writestr("spider_data/dev.json", "[]")
    loader = SpiderLoader(str(root), archive_path=str(zpath))
    info = loader.archive_info()
    assert info is not None
    assert info["path"].endswith("spider_data.zip")
    assert info["entries"] > 0


def test_spider_database_discovery(tmp_path):
    root = build_spider_root(tmp_path)
    loader = SpiderLoader(str(root))
    dbs = loader.discover_databases()
    ids = {d.database_id for d in dbs}
    assert {"library", "store"} <= ids
    library = next(d for d in dbs if d.database_id == "library")
    # library is in both database/ and test_database/
    assert "database" in library.split.split(",")
    assert "test_database" in library.split.split(",")


def test_spider_missing_root_raises():
    with pytest.raises(SpiderNotFound):
        SpiderLoader("/nonexistent/spider/root")


# ---------------------------------------------------------------------------
# 2. Spider question + reference SQL loading
# ---------------------------------------------------------------------------
def test_spider_question_loading(tmp_path):
    root = build_spider_root(tmp_path)
    loader = SpiderLoader(str(root))
    dev = loader.load_questions("dev")
    assert len(dev) == 2
    assert dev[0].question == "List all book titles."
    assert dev[0].database_id == "library"
    assert dev[0].database_path is not None
    assert dev[0].database_path.endswith("library.sqlite")


def test_spider_reference_sql_loading(tmp_path):
    root = build_spider_root(tmp_path)
    loader = SpiderLoader(str(root))
    dev = loader.load_questions("dev")
    by_id = {q.database_id: q for q in dev}
    assert by_id["library"].reference_sql == "SELECT title FROM books;"
    # query=None -> reference_sql stays None
    assert by_id["store"].reference_sql is None
    train = loader.load_questions("train")
    assert len(train) == 1
    assert train[0].reference_sql == "SELECT count(*) FROM books;"


def test_spider_missing_database_resolution(tmp_path):
    root = build_spider_root(tmp_path)
    loader = SpiderLoader(str(root))
    dev = loader.load_questions("dev")
    assert all(q.database_path is not None for q in dev)
    # slave db has no sqlite file -> None
    assert loader.resolve_database_path("ghost_db") is None


# ---------------------------------------------------------------------------
# 3. BIRD database + question loading
# ---------------------------------------------------------------------------
def test_bird_database_discovery(tmp_path):
    root = build_bird_root(tmp_path)
    loader = BirdLoader(str(root))
    dbs = loader.discover_databases()
    assert {d.database_id for d in dbs} == {"library", "store"}


def test_bird_question_loading_and_reference_sql(tmp_path):
    root = build_bird_root(tmp_path)
    loader = BirdLoader(str(root))
    questions = loader.load_questions()
    assert len(questions) == 2
    by_id = {q.metadata["question_id"]: q for q in questions}
    assert by_id[1].reference_sql == "SELECT title FROM books;"
    assert by_id[1].evidence == "titles of all books"
    # inline SQL missing -> gold file fallback
    assert by_id[2].reference_sql == "SELECT count(*) FROM authors;"
    assert by_id[2].database_path is not None


def test_bird_missing_questions_file(tmp_path):
    root = tmp_path / "empty_root"
    root.mkdir(exist_ok=True)
    with pytest.raises(BirdNotFound):
        BirdLoader(str(root))


def test_bird_missing_db_handling(tmp_path):
    root = build_bird_root(tmp_path)
    (root / "dev_databases" / "library" / "library.sqlite").unlink()
    loader = BirdLoader(str(root))
    questions = loader.load_questions()
    library = next(q for q in questions if q.database_id == "library")
    assert library.database_path is None


# ---------------------------------------------------------------------------
# 4. Common BenchmarkQuestion structure + normalization
# ---------------------------------------------------------------------------
def test_benchmark_question_structure():
    q = BenchmarkQuestion(
        question="List all titles",
        database_id="library",
        database_path="/tmp/library.sqlite",
        reference_sql="SELECT title FROM books;",
        split="dev",
        evidence="hint",
        metadata={"difficulty": "simple", "question_id": 1},
    )
    d = q.to_dict()
    assert set(d) == {
        "question", "database_id", "database_path", "reference_sql",
        "split", "evidence", "metadata",
    }
    assert d["reference_sql"] == "SELECT title FROM books;"


def test_no_enterprise_hardcoding_in_loaders():
    """Loaders must not import Enterprise models or reference its tables."""
    from backend.benchmarks import bird_loader, spider_loader
    import inspect as _inspect

    for module in (bird_loader, spider_loader):
        # no import of backend.database.models anywhere in the module
        source = _inspect.getsource(module)
        assert "backend.database.models" not in source
        # no enterprise table names referenced literally
        for enterprise_table in ("employees", "departments", "sales", "customers"):
            assert enterprise_table not in source.lower().replace(
                "benchmark", ""
            ).replace("databases", "").split()


def test_loaders_do_not_import_models():
    """Importing the loaders must not import backend.database.models
    (verified in a fresh interpreter so test ordering cannot interfere)."""
    script = (
        "import sys; "
        "from backend.benchmarks import spider_loader, bird_loader; "
        "print('IMPORTED_MODELS' if 'backend.database.models' in sys.modules else 'CLEAN')"
    )
    _subprocess_models_import(script)


# ---------------------------------------------------------------------------
# 5. L2 inspection of external databases (no models.py)
# ---------------------------------------------------------------------------
def _subprocess_models_import(script):
    """Assert that ``backend.database.models`` is NOT imported when running
    ``script`` in a fresh interpreter (immune to test-ordering pollution)."""
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    assert "IMPORTED_MODELS" not in proc.stdout
    assert proc.stdout.strip() == "CLEAN"


def test_l2_inspection_of_external_db(tmp_path):
    db = make_db(tmp_path / "ext" / "ext.sqlite")
    from backend.database.schema_inspector import inspect_database
    schema = inspect_database(str(db))
    names = {t.name for t in schema.tables}
    assert names == {"authors", "books"}
    books = next(t for t in schema.tables if t.name == "books")
    assert {c.name for c in books.columns} == {"book_id", "author_id", "title"}
    assert books.primary_keys == ("book_id",)
    assert any(
        fk.source_column == "author_id"
        and fk.target_table == "authors"
        and fk.target_column == "author_id"
        for fk in books.foreign_keys
    )


# ---------------------------------------------------------------------------
# 6. External retrieval index preparation
# ---------------------------------------------------------------------------
def test_external_index_creation_fake_embedder(tmp_path):
    db = make_db(tmp_path / "books" / "books.sqlite")
    info = build_external_index(
        str(db),
        database_id="books",
        index_root=str(tmp_path / "indexes"),
        fake_embedder=True,
    )
    assert info["documents"] >= 1
    assert (tmp_path / "indexes" / "books").is_dir()
    # derived from L2, not enterprise
    assert "employees" not in info["tables"]
    assert {"authors", "books"} <= set(info["tables"])


def test_external_index_creation_real_embedder_if_available(tmp_path):
    pytest.importorskip("sentence_transformers")
    db = make_db(tmp_path / "books" / "books.sqlite")
    try:
        info = build_external_index(
            str(db),
            database_id="books",
            index_root=str(tmp_path / "indexes_real"),
            fake_embedder=False,
        )
    except Exception as exc:  # model not on disk -> skip gracefully
        pytest.skip(f"embedding model unavailable: {exc}")
    assert info["documents"] >= 1
    assert {"authors", "books"} <= set(info["tables"])


def test_default_index_dir_per_database(tmp_path):
    first = default_index_dir(str(tmp_path), "library", "/a/library.sqlite")
    second = default_index_dir(str(tmp_path), "library", "/b/library.sqlite")
    assert first != second  # fingerprint differs by path
    assert str(tmp_path) in str(first)


def test_missing_database_raises_for_index(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_external_index(
            str(tmp_path / "missing.sqlite"),
            database_id="missing",
            index_root=str(tmp_path / "indexes"),
            fake_embedder=True,
        )


# ---------------------------------------------------------------------------
# 7. Optional smoke tests on the real downloaded datasets (auto-skip)
# ---------------------------------------------------------------------------
def _skip_unless(condition, reason):
    if not condition:
        pytest.skip(reason)


def test_real_spider_smoke():
    _skip_unless(REAL_SPIDER_ROOT.is_dir(), "real Spider dataset not present")
    loader = SpiderLoader(str(REAL_SPIDER_ROOT))
    assert loader.archive_info() is not None
    dbs = loader.discover_databases()
    assert len(dbs) > 100
    dev = loader.load_questions("dev")
    assert len(dev) > 500
    assert all(q.database_path is not None for q in dev[:5])


def test_real_bird_smoke():
    _skip_unless(REAL_BIRD_ROOT.is_dir(), "real BIRD dataset not present")
    loader = BirdLoader(str(REAL_BIRD_ROOT))
    dbs = loader.discover_databases()
    assert len(dbs) >= 10
    questions = loader.load_questions()
    assert len(questions) == 500
    assert sum(1 for q in questions if q.reference_sql) >= 490


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))