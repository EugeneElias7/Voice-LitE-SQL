"""Voice-LitE-SQL -- Level 7: relationship-aware schema retrieval.

Given a natural-language question, returns the top-K relevant schema
documents from the ChromaDB index and performs a deterministic relationship
expansion step:

- when a column document is retrieved, any foreign key that starts or ends
  at that column is surfaced as an additional relationship document
- when a relationship document is retrieved, the referenced column is
  guaranteed to be included too

This makes JOIN questions see not just the individual columns but also the
FK edges that connect them.
"""

from dataclasses import dataclass, field

from backend.retrieval.chroma_store import DEFAULT_COLLECTION_NAME, SchemaIndex
from backend.retrieval.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    SentenceTransformerEmbedder,
)
from backend.retrieval.schema_documents import (
    COLUMN_DOC,
    RELATIONSHIP_DOC,
    TABLE_DOC,
    SchemaDocument,
    documents_by_id,
    generate_schema_documents,
)


@dataclass
class RetrievedItem:
    """One returned schema item with provenance and score."""

    doc_type: str
    doc_id: str
    table: str = ""
    column: str = ""
    fk_source_table: str = ""
    fk_source_column: str = ""
    fk_target_table: str = ""
    fk_target_column: str = ""
    text: str = ""
    score: float = 0.0
    distance: float = 1.0
    source: str = "retrieval"  # 'retrieval' | 'relationship_expansion'

    def to_dict(self):
        return {
            "doc_type": self.doc_type,
            "doc_id": self.doc_id,
            "table": self.table,
            "column": self.column,
            "fk_source_table": self.fk_source_table,
            "fk_source_column": self.fk_source_column,
            "fk_target_table": self.fk_target_table,
            "fk_target_column": self.fk_target_column,
            "text": self.text,
            "score": round(self.score, 6),
            "distance": round(self.distance, 6),
            "source": self.source,
        }


@dataclass
class RetrievalResult:
    """Structured output of one retrieval step."""

    question: str
    top_k: int
    items: list = field(default_factory=list)
    schema_context_text: str = ""

    def to_dict(self):
        return {
            "question": self.question,
            "top_k": self.top_k,
            "items": [item.to_dict() for item in self.items],
            "schema_context": self.schema_context_text,
        }

    @property
    def primary_items(self):
        return [item for item in self.items if item.source == "retrieval"]

    @property
    def relationship_items(self):
        return [item for item in self.items if item.doc_type == RELATIONSHIP_DOC]


class SchemaRetriever:
    """Builds a persistent schema index and answers questions with it.

    Parameters
    ----------
    db_path:
        path to an arbitrary SQLite database (driven by L2 inspector).
    persist_dir:
        directory where ChromaDB persists the schema index.
    collection_name:
        ChromaDB collection name (configurable).
    embedding_model:
        sentence-transformers model id, already available locally.
    embedding_dimensions:
        dimension of the embedding vectors for this model.
    top_k:
        default number of primary documents to retrieve.
    embedder:
        optional embedder override (tests inject a fake). Defaults to
        :class:`SentenceTransformerEmbedder`.
    """

    def __init__(
        self,
        db_path,
        persist_dir,
        collection_name=DEFAULT_COLLECTION_NAME,
        embedding_model=DEFAULT_EMBEDDING_MODEL,
        embedding_dimensions=384,
        top_k=5,
        embedder=None,
    ):
        self.db_path = db_path
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.top_k = top_k

        self._embedder = embedder or SentenceTransformerEmbedder(
            model_name=embedding_model
        )
        self._documents = generate_schema_documents(db_path)
        self._document_by_id = documents_by_id(self._documents)

        self.index = SchemaIndex(
            persist_dir=persist_dir,
            collection_name=collection_name,
            embedding_dimensions=embedding_dimensions,
        )
        self._index_built = False

    # ------------------------------------------------------------------
    @property
    def documents(self):
        """All schema documents generated for this database."""
        return list(self._documents)

    def build_index(self):
        """Embed and index all schema documents (idempotent)."""
        if not self._index_built:
            self.index.add_documents(self._documents, self._embedder)
            self._index_built = True
        return self.index.count()

    # ------------------------------------------------------------------
    def _match_relationships(self, doc):
        """Return the relationship documents attached to ``doc``.

        - a column doc returns relationships where that column is an endpoint
        - a relationship doc returns itself plus the referenced column doc
        """
        if doc.doc_type == COLUMN_DOC:
            return [
                candidate
                for candidate in self._documents
                if candidate.doc_type == RELATIONSHIP_DOC
                and (
                    (
                        candidate.fk_source_table == doc.table
                        and candidate.fk_source_column == doc.column
                    )
                    or (
                        candidate.fk_target_table == doc.table
                        and candidate.fk_target_column == doc.column
                    )
                )
            ]
        if doc.doc_type == RELATIONSHIP_DOC:
            referenced = self._document_by_id.get(
                column_doc_id(
                    doc.fk_target_table, doc.fk_target_column
                )
            )
            return [item for item in [doc, referenced] if item is not None]
        return []

    def retrieve(self, question, top_k=None):
        """Retrieve the schema relevant to ``question``.

        Returns a :class:`RetrievalResult` with the primary top-K matches
        followed by deterministic relationship-expansion items. Deduplicates
        by document ID and keeps stable order.
        """
        top_k = top_k if top_k is not None else self.top_k
        self.build_index()

        embedding = self._embedder.encode([question])[0]
        hits = self.index.query(list(embedding), top_k=top_k)

        seen_ids = set()
        items = []
        for hit in hits:
            doc = self._document_by_id.get(hit["doc_id"])
            if doc is None:
                continue
            item = self._from_document(doc, hit)
            if item.doc_id in seen_ids:
                continue
            seen_ids.add(item.doc_id)
            items.append(item)

            for related in self._match_relationships(doc):
                if related.doc_id in seen_ids:
                    continue
                seen_ids.add(related.doc_id)
                items.append(
                    self._from_document(
                        related,
                        {"score": hit["score"], "distance": hit["distance"]},
                        source="relationship_expansion",
                    )
                )

        return RetrievalResult(
            question=question,
            top_k=top_k,
            items=items,
            schema_context_text=format_schema_context(items),
        )

    @staticmethod
    def _from_document(document, hit, source="retrieval"):
        text = document.text
        return RetrievedItem(
            doc_type=document.doc_type,
            doc_id=document.doc_id,
            table=document.table,
            column=document.column,
            fk_source_table=document.fk_source_table,
            fk_source_column=document.fk_source_column,
            fk_target_table=document.fk_target_table,
            fk_target_column=document.fk_target_column,
            text=text,
            score=hit.get("score", 0.0),
            distance=hit.get("distance", 1.0),
            source=source,
        )


def column_doc_id(table, column):
    from backend.retrieval.schema_documents import column_document_id

    return column_document_id(table, column)


def format_schema_context(items):
    """Render retrieved items into the block used inside the L7 prompt."""
    blocks = []
    for item in items:
        if item.doc_type == RELATIONSHIP_DOC:
            blocks.append(
                f"RELATIONSHIP: {item.fk_source_table}.{item.fk_source_column}"
                f" -> {item.fk_target_table}.{item.fk_target_column}"
            )
        else:
            blocks.append(item.text)
    return "\n".join(blocks)