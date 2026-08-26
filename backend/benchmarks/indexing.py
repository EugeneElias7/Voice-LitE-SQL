"""Voice-LitE-SQL -- Level 10: per-database external retrieval index.

Builds a separate ChromaDB retrieval index for an arbitrary external SQLite
database. Schema documents are generated exclusively from the L2 Schema
Inspector output (never from Enterprise metadata), so no Enterprise schema
can leak into an external benchmark retrieval index.

The design reuses the existing L7 ``SchemaRetriever`` so retrieval behaviour
stays identical to the L9 pipeline while the storage location and content
are fully separated per database.
"""

import hashlib
from pathlib import Path
from typing import Optional

from backend.retrieval import (
    DEFAULT_EMBEDDING_MODEL,
    CountVectorEmbedder,
    SchemaRetriever,
    SentenceTransformerEmbedder,
)
from backend.retrieval.embeddings import EMBEDDING_DIMENSIONS

DEFAULT_INDEX_ROOT = (
    Path(__file__).resolve().parents[2] / "datasets" / "external" / "indexes"
)


def _safe_name(database_id: str) -> str:
    """Sanitize a database id into a filesystem-safe directory name."""
    name = "".join(c if c.isalnum() or c in "-_." else "_" for c in database_id)
    return name or "unnamed"


def _db_fingerprint(database_path: str) -> str:
    """Short content-independent hash used only to make index paths unique."""
    return hashlib.sha1(str(database_path).encode("utf-8")).hexdigest()[:10]


def default_index_dir(
    index_root: str = str(DEFAULT_INDEX_ROOT),
    database_id: str = "db",
    database_path: str = None,
) -> Path:
    """Determine the index directory for one external database.

    A per-database subdirectory avoids sharing a single index across the
    enterprise database and external benchmarks.
    """
    root = Path(index_root)
    if database_path:
        sub = Path(_safe_name(database_id)) / _db_fingerprint(database_path)
    else:
        sub = Path(_safe_name(database_id))
    return root / sub


def build_external_index(
    database_path: str,
    database_id: str = "db",
    split: str = "",
    index_root: str = str(DEFAULT_INDEX_ROOT),
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    top_k: int = 5,
    fake_embedder: bool = False,
) -> dict:
    """Generate schema documents (via L2) and build a retrieval index.

    Returns a dict describing what was built so callers can verify without
    running any benchmark evaluation:

    - ``database_id``, ``database_path``
    - ``index_dir`` persisted ChromaDB location
    - ``documents`` number of schema documents embedded
    - ``tables`` number of tables discovered by L2
    - ``collection`` ChromaDB collection name
    """
    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(f"database not found: {path}")

    persist_dir = default_index_dir(index_root, database_id, str(path))
    persist_dir.mkdir(parents=True, exist_ok=True)

    embedder = (
        CountVectorEmbedder(dimensions=384)
        if fake_embedder
        else SentenceTransformerEmbedder(model_name=embedding_model)
    )

    retriever = SchemaRetriever(
        db_path=str(path),
        persist_dir=str(persist_dir),
        embedding_model=embedding_model,
        embedding_dimensions=EMBEDDING_DIMENSIONS.get(embedding_model, 384),
        top_k=top_k,
        embedder=embedder,
    )

    retriever.build_index()
    schema = retriever.documents  # noqa: F841 - documented below via inspector
    # Gather L2-discovered tables for the report.
    from backend.database.schema_inspector import inspect_database

    inspected = inspect_database(str(path))
    table_names = [t.name for t in inspected.tables]

    return {
        "database_id": database_id,
        "database_path": str(path),
        "split": split,
        "index_dir": str(persist_dir),
        "documents": len(schema),
        "tables": table_names,
        "collection": "schema_index",
        "embedding_model": embedding_model,
    }