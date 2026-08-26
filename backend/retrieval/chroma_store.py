"""Voice-LitE-SQL -- Level 7: ChromaDB-backed schema index.

A thin, reusable wrapper around a persistent ChromaDB collection. Only
schema metadata (documents) is indexed -- never actual database rows.

Guarantees provided by this module:

- persistent local storage (only schema metadata is persisted)
- configurable collection name
- deterministic document IDs (upsert, so repeated indexing never duplicates)
- rebuild/update capability (idempotent)
- top-K similarity queries with metadata returned intact
"""

import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import chromadb  # noqa: E402
from chromadb.config import Settings  # noqa: E402

DEFAULT_COLLECTION_NAME = "schema_index"


class SchemaIndexError(RuntimeError):
    """Raised when the ChromaDB-backed index cannot be used."""


class SchemaIndex:
    """Persistent ChromaDB collection for schema documents.

    Parameters
    ----------
    persist_dir:
        local directory where ChromaDB persists its data.
    collection_name:
        name of the collection inside ChromaDB (configurable).
    embedding_dimensions:
        dimension of the embedding vectors; must match the embedder in use.
    """

    def __init__(
        self,
        persist_dir,
        collection_name=DEFAULT_COLLECTION_NAME,
        embedding_dimensions=768,
    ):
        try:
            self._client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=Settings(anonymized_telemetry=False),
            )
        except Exception as exc:  # noqa: BLE001 - surface any Chroma failure
            raise SchemaIndexError(
                f"cannot open ChromaDB at {persist_dir}: {exc}"
            ) from exc

        self.collection_name = collection_name
        self.embedding_dimensions = embedding_dimensions
        self.collection = self._get_or_create_collection()

    def _get_or_create_collection(self):
        try:
            return self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:  # noqa: BLE001
            raise SchemaIndexError(
                f"cannot create collection '{self.collection_name}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    def count(self):
        return self.collection.count()

    def list_ids(self):
        """All document IDs currently in the index (sorted)."""
        data = self.collection.get(include=[])
        return sorted(data.get("ids", []))

    def reset(self):
        """Drop everything from the collection and recreate it."""
        try:
            self._client.delete_collection(self.collection_name)
        except Exception:  # noqa: BLE001 - not present yet is fine
            pass
        self.collection = self._get_or_create_collection()

    # ------------------------------------------------------------------
    def add_documents(self, documents, embedder):
        """Idempotently index schema documents.

        ``documents`` is an iterable of objects exposing ``doc_id`` and
        ``text``. Embeddings are computed by ``embedder.encode``. Upsert by
        deterministic ``doc_id`` means repeated indexing never duplicates.
        """
        docs = list(documents)
        ids = [doc.doc_id for doc in docs]
        texts = [doc.text for doc in docs]

        if hasattr(embedder, "fit"):
            embedder.fit(texts)
        embeddings = embedder.encode(texts)

        own_embeddings = [
            [float(value) for value in row] for row in embeddings[: len(ids)]
        ]
        self.collection.upsert(
            ids=ids,
            documents=texts,
            embeddings=own_embeddings,
        )
        return len(ids)

    # ------------------------------------------------------------------
    def query(self, query_embedding, top_k=5):
        """Return the top-k schema documents nearest to ``query_embedding``.

        ChromaDB stores distance (1 - cosine similarity); results are
        returned as a list of dicts with ``doc_id``, ``text``, ``score``
        (1 - distance, higher = more similar) and the raw ``distance``.
        """
        if top_k is None:
            top_k = 5
        result = self.collection.query(
            query_embeddings=[[float(v) for v in query_embedding]],
            n_results=top_k,
            include=["documents", "distances", "metadatas"],
        )
        ids = (result.get("ids") or [[]])[0]
        texts = (result.get("documents") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]

        out = []
        for doc_id, text, distance, metadata in zip(
            ids, texts, distances, metadatas
        ):
            out.append(
                {
                    "doc_id": doc_id,
                    "text": text,
                    "distance": round(float(distance), 6),
                    "score": round(1.0 - float(distance), 6),
                    "metadata": metadata or {},
                }
            )
        return out