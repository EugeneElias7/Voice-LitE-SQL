"""Voice-LitE-SQL -- Level 7: database-aware vector schema retrieval.

Public API for the L7 retrieval package: schema documents -> embeddings ->
ChromaDB index -> relationship-aware retrieval -> schema-grounded prompt.
"""

from backend.retrieval.chroma_store import (
    DEFAULT_COLLECTION_NAME,
    SchemaIndex,
    SchemaIndexError,
)
from backend.retrieval.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    CountVectorEmbedder,
    EmbeddingError,
    SentenceTransformerEmbedder,
)
from backend.retrieval.prompt import build_l7_prompt
from backend.retrieval.schema_documents import (
    COLUMN_DOC,
    RELATIONSHIP_DOC,
    TABLE_DOC,
    SchemaDocument,
    generate_schema_documents,
)
from backend.retrieval.schema_retriever import (
    RetrievalResult,
    RetrievedItem,
    SchemaRetriever,
    format_schema_context,
)

__all__ = [
    "COLUMN_DOC",
    "CountVectorEmbedder",
    "DEFAULT_COLLECTION_NAME",
    "DEFAULT_EMBEDDING_MODEL",
    "EmbeddingError",
    "RELATIONSHIP_DOC",
    "RetrievalResult",
    "RetrievedItem",
    "SchemaDocument",
    "SchemaIndex",
    "SchemaIndexError",
    "SchemaRetriever",
    "SentenceTransformerEmbedder",
    "TABLE_DOC",
    "build_l7_prompt",
    "format_schema_context",
    "generate_schema_documents",
]