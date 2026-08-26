"""Voice-LitE-SQL -- Level 7 tests: schema retrieval / schema linking.

Covers the retrieval package with a mocked (deterministic, dependency-free)
embedder so the pipeline is fully exercised without a live embedding model.
"""

import sqlite3
import uuid
from pathlib import Path

import pytest

from backend.database.executor import execute_sql
from backend.retrieval import (
    CountVectorEmbedder,
    SchemaIndex,
    SchemaRetriever,
    build_l7_prompt,
    generate_schema_documents,
)
from backend.retrieval.chroma_store import DEFAULT_COLLECTION_NAME
from backend.retrieval.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    SentenceTransformerEmbedder,
)
from backend.retrieval.schema_documents import (
    COLUMN_DOC,
    RELATIONSHIP_DOC,
    TABLE_DOC,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "backend" / "data" / "enterprise.db"

# Schema of the temporary (not enterprise) database used by many tests.
TEMP_SCHEMA_SQL = """
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
"""

FAKE_EMBEDDER = CountVectorEmbedder(dimensions=384)


def make_temp_db(tmp_path, name="books.db", sql=TEMP_SCHEMA_SQL):
    db = tmp_path / name
    conn = sqlite3.connect(str(db))
    conn.executescript(sql)
    conn.commit()
    conn.close()
    return db


def new_persist_dir(tmp_path):
    return tmp_path / f"chroma-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# 1. Schema documents (from L2, no models.py dependency)
# ---------------------------------------------------------------------------

def test_schema_documents_generated_from_inspector():
    docs = generate_schema_documents(DB_PATH)
    ids = [doc.doc_id for doc in docs]
    assert len(ids) > 0
    # enterprise.db has 7 tables, 34 columns, 8 FKs -> 49 documents
    assert len(docs) == 49
    assert len({doc.doc_id for doc in docs}) == len(docs)  # unique
    # all document types present
    assert TABLE_DOC in {d.doc_type for d in docs}
    assert COLUMN_DOC in {d.doc_type for d in docs}
    assert RELATIONSHIP_DOC in {d.doc_type for d in docs}


def test_schema_documents_not_based_on_models(tmp_path):
    db = make_temp_db(tmp_path)
    docs = generate_schema_documents(db)
    tables = {doc.table for doc in docs}
    assert {"authors", "books"} <= tables
    assert "employees" not in tables  # temp db, not enterprise


def test_table_document_content(tmp_path):
    db = make_temp_db(tmp_path)
    docs = generate_schema_documents(db)
    authors = next(d for d in docs if d.doc_id == "table:authors")
    assert authors.text.startswith("TABLE: authors")
    assert "author_id INTEGER PRIMARY KEY" in authors.text
    assert "author_name TEXT" in authors.text


def test_column_document_content(tmp_path):
    db = make_temp_db(tmp_path)
    docs = generate_schema_documents(db)
    col = next(d for d in docs if d.doc_id == "column:books.author_id")
    assert "COLUMN: books.author_id" in col.text
    assert "TYPE: INTEGER" in col.text


def test_relationship_document_content(tmp_path):
    db = make_temp_db(tmp_path)
    docs = generate_schema_documents(db)
    rel = next(d for d in docs if d.doc_type == RELATIONSHIP_DOC)
    assert rel.fk_source_table == "books"
    assert rel.fk_source_column == "author_id"
    assert rel.fk_target_table == "authors"
    assert rel.fk_target_column == "author_id"
    assert "books.author_id" in rel.text
    assert "authors.author_id" in rel.text


# ---------------------------------------------------------------------------
# 2. Deterministic document IDs
# ---------------------------------------------------------------------------

def test_document_ids_deterministic(tmp_path):
    db = make_temp_db(tmp_path)
    first = [d.doc_id for d in generate_schema_documents(db)]
    second = [d.doc_id for d in generate_schema_documents(db)]
    assert first == second


def test_relationship_id_deterministic_naming():
    db_ids = {d.doc_id for d in generate_schema_documents(DB_PATH)}
    assert "relationship:employees.department_id->departments.department_id" in db_ids
    assert "relationship:sales.employee_id->employees.employee_id" in db_ids


# ---------------------------------------------------------------------------
# 3. ChromaDB index
# ---------------------------------------------------------------------------

def test_index_persistent_and_reenumerable(tmp_path):
    persist = new_persist_dir(tmp_path)
    docs = generate_schema_documents(DB_PATH)
    index = SchemaIndex(persist, embedding_dimensions=384)
    index.add_documents(docs, FAKE_EMBEDDER)
    assert index.count() == len(docs)

    reopened = SchemaIndex(persist, embedding_dimensions=384)
    assert reopened.count() == len(docs)  # persisted across instances


def test_indexing_repeatable_no_duplicates(tmp_path):
    persist = new_persist_dir(tmp_path)
    docs = generate_schema_documents(DB_PATH)
    index = SchemaIndex(persist, embedding_dimensions=384)
    index.add_documents(docs, FAKE_EMBEDDER)
    index.add_documents(docs, FAKE_EMBEDDER)  # upsert same docs again
    assert index.count() == len(docs)  # no duplicates
    assert len(index.list_ids()) == len(docs)
    assert len(set(index.list_ids())) == len(index.list_ids())


def test_index_collection_name_configurable(tmp_path):
    persist = new_persist_dir(tmp_path)
    index = SchemaIndex(
        persist, collection_name="my_schema", embedding_dimensions=384
    )
    assert index.collection_name == "my_schema"
    assert index.collection.name == "my_schema"


def test_index_reset(tmp_path):
    persist = new_persist_dir(tmp_path)
    docs = generate_schema_documents(DB_PATH)
    index = SchemaIndex(persist, embedding_dimensions=384)
    index.add_documents(docs, FAKE_EMBEDDER)
    assert index.count() == len(docs)
    index.reset()
    assert index.count() == 0


def test_chroma_query_top_k(tmp_path):
    persist = new_persist_dir(tmp_path)
    docs = generate_schema_documents(DB_PATH)
    index = SchemaIndex(persist, embedding_dimensions=384)
    index.add_documents(docs, FAKE_EMBEDDER)
    q = FAKE_EMBEDDER.encode(["salary"])[0]
    for top_k in (1, 3, 5):
        hits = index.query(q, top_k=top_k)
        assert len(hits) == top_k
    # cosine distance in [0, 2], score = 1 - distance
    for hit in hits:
        assert 0.0 <= hit["distance"] <= 2.0
        assert hit["score"] == round(1.0 - hit["distance"], 6)


def test_irrelevant_schema_not_unnecessarily_retrieved(tmp_path):
    persist = new_persist_dir(tmp_path)
    docs = generate_schema_documents(DB_PATH)
    index = SchemaIndex(persist, embedding_dimensions=384)
    index.add_documents(docs, FAKE_EMBEDDER)
    q = FAKE_EMBEDDER.encode(["average salary"])[0]
    hits = index.query(q, top_k=3)
    # salary-column document must be the top hit
    assert hits[0]["doc_id"] == "column:employees.salary"
    assert "salary" in hits[0]["text"].lower()


# ---------------------------------------------------------------------------
# 4. End-to-end retrieval (mocked embedder)
# ---------------------------------------------------------------------------

def test_retriever_build_index_and_retrieve(tmp_path):
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        "%s" % DB_PATH,
        persist_dir=persist,
        embedding_dimensions=384,
        embedder=FAKE_EMBEDDER,
    )
    count = retriever.build_index()
    assert count == 49
    result = retriever.retrieve("list employee names", top_k=5)
    assert result.items
    for item in result.items:
        assert item.doc_id
        assert item.text


def test_retriever_top_k_configurable(tmp_path):
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH),
        persist_dir=persist,
        embedding_dimensions=384,
        top_k=3,
        embedder=FAKE_EMBEDDER,
    )
    result = retriever.retrieve("list employee names")
    assert result.top_k == 3
    assert len(result.primary_items) == 3


def test_retriever_relevant_column_retrieved(tmp_path):
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH),
        persist_dir=persist,
        embedding_dimensions=384,
        top_k=5,
        embedder=FAKE_EMBEDDER,
    )
    result = retriever.retrieve("List all employee names.")
    ids = [i.doc_id for i in result.items]
    assert "column:employees.employee_name" in ids


def test_retriever_table_information_retrieved(tmp_path):
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH),
        persist_dir=persist,
        embedding_dimensions=384,
        top_k=5,
        embedder=FAKE_EMBEDDER,
    )
    result = retriever.retrieve("Which customers live in a city?")
    ids = [i.doc_id for i in result.primary_items]
    assert "table:customers" in ids or "column:customers.city" in ids


def test_fk_relationship_expansion_works(tmp_path):
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(DB_PATH),
        persist_dir=persist,
        embedding_dimensions=384,
        top_k=5,
        embedder=FAKE_EMBEDDER,
    )
    # departments is referenced by employees.department_id FK
    result = retriever.retrieve("average salary by department")
    rel_ids = [i.doc_id for i in result.relationship_items]
    assert "relationship:employees.department_id->departments.department_id" in rel_ids


def test_relationship_expansion_deterministic(tmp_path):
    persist_a = new_persist_dir(tmp_path)
    persist_b = new_persist_dir(tmp_path)
    retriever_a = SchemaRetriever(
        str(DB_PATH), persist_dir=persist_a, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    retriever_b = SchemaRetriever(
        str(DB_PATH), persist_dir=persist_b, embedding_dimensions=384,
        top_k=5, embedder=FAKE_EMBEDDER,
    )
    result_a = retriever_a.retrieve("average salary by department")
    result_b = retriever_b.retrieve("average salary by department")
    assert [i.doc_id for i in result_a.items] == [i.doc_id for i in result_b.items]


def test_retriever_works_on_independent_temp_db(tmp_path):
    db = make_temp_db(tmp_path)
    persist = new_persist_dir(tmp_path)
    retriever = SchemaRetriever(
        str(db),
        persist_dir=persist,
        embedding_dimensions=384,
        top_k=5,
        embedder=FAKE_EMBEDDER,
    )
    count = retriever.build_index()
    assert count > 0
    result = retriever.retrieve("Which author wrote which book?")
    ids = [i.doc_id for i in result.items]
    assert any("authors" in i for i in ids) or any("books" in i for i in ids)


# ---------------------------------------------------------------------------
# 5. L7 prompt
# ---------------------------------------------------------------------------

def test_prompt_contains_question():
    prompt = build_l7_prompt("What is the average salary?", "COLUMN: employees.salary")
    assert "What is the average salary?" in prompt


def test_prompt_contains_retrieved_schema():
    prompt = build_l7_prompt("Q", "COLUMN: employees.salary")
    assert "RETRIEVED SCHEMA" in prompt
    assert "COLUMN: employees.salary" in prompt


def test_prompt_prohibits_invented_tables_columns():
    prompt = build_l7_prompt("Q", "COLUMN: employees.salary")
    assert "Do not invent tables or columns" in prompt


def test_prompt_forbids_destructive_operations():
    prompt = build_l7_prompt("Q", "COLUMN: employees.salary")
    assert "INSERT" in prompt
    assert "UPDATE" in prompt
    assert "DELETE" in prompt


def test_prompt_includes_relationship_context():
    context = (
        "RELATIONSHIP: employees.department_id "
        "-> departments.department_id"
    )
    prompt = build_l7_prompt("average salary by department", context)
    assert context in prompt
    assert "foreign key relationships" in prompt


# ---------------------------------------------------------------------------
# 6. Fair comparison: L4 executor + existing semantics unchanged
# ---------------------------------------------------------------------------

def test_l4_executor_unchanged_read_only():
    # the exact executor used by L4 works, rejects writes
    result = execute_sql("SELECT department_name FROM departments;", str(DB_PATH))
    assert result.success
    result = execute_sql("DELETE FROM departments;", str(DB_PATH))
    assert not result.success
    assert result.error_type == "validation_error"


def test_embedder_configurable_offline_missing_model():
    # missing local model -> EmbeddingError, no download attempt
    with pytest.raises(Exception):
        SentenceTransformerEmbedder(
            model_name="nonexistent-model-does-not-exist"
        )


def test_count_vector_embedder_deterministic():
    a = FAKE_EMBEDDER.encode(["salary by department"])
    b = FAKE_EMBEDDER.encode(["salary by department"])
    assert a == b
    # output is a list of float vectors with stable dimension
    assert len(a[0]) == FAKE_EMBEDDER.dimensions