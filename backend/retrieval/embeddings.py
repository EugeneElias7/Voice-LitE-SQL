"""Voice-LitE-SQL -- Level 7: configurable embedding provider.

Wraps the project's existing sentence-transformers dependency. The model
name is configurable (``embedding_model``). Models are never downloaded from
inside the application: loading uses ``local_files_only=True`` so a missing
model raises a clear error instead of silently fetching from the network.

The embedder only needs to expose a ``encode`` method, so tests can inject
a fake embedder and exercise the retrieval pipeline without any external
service.
"""

import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = {
    "all-MiniLM-L6-v2": 384,
}


class EmbeddingError(RuntimeError):
    """Raised when the embedding model is unavailable or fails."""


class SentenceTransformerEmbedder:
    """Configurable sentence-transformers embedder.

    Parameters from kwargs (kept minimal on purpose):
        model_name: huggingface model id already present in the local cache
        device: torch device ('cpu' by default)
        normalize: L2-normalize embeddings (cosine similarity)
    """

    def __init__(
        self,
        model_name=DEFAULT_EMBEDDING_MODEL,
        device="cpu",
        normalize=True,
    ):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - env issue
            raise EmbeddingError(
                "sentence-transformers is not installed. "
                "Install project dependencies before running L7."
            ) from exc

        self.model_name = model_name
        self.device = device
        self.normalize = normalize
        try:
            self._model = SentenceTransformer(
                model_name,
                device=device,
                local_files_only=True,
            )
        except Exception as exc:  # noqa: BLE001 - surface any load failure
            raise EmbeddingError(
                f"embedding model '{model_name}' is not available locally: {exc}"
            ) from exc

    def encode(self, texts):
        import numpy as np

        if isinstance(texts, str):
            texts = [texts]
        vectors = self._model.encode(texts, normalize_embeddings=self.normalize)
        return np.asarray(vectors, dtype="float32")

    @property
    def dimensions(self):
        return EMBEDDING_DIMENSIONS.get(self.model_name, 384)


class CountVectorEmbedder:
    """Deterministic, dependency-free embedder for tests/offline runs.

    A TF-IDF weighted hashing embedder: each cleaned token is mapped to a
    fixed dimension index and weighted by ``count * idf``, where ``idf`` is
    the inverse document frequency learned from the corpus via :meth:`fit`.
    Rare schema tokens (e.g. ``salary``) influence cosine similarity much
    more than common words, so mocked retrieval behaves semantically without
    sentence-transformers or a live model.

    Calling :meth:`fit` with the same corpus always produces the same IDF
    weights, which keeps the embedder deterministic across retrievers.
    """

    def __init__(self, dimensions=384):
        self.dimensions = dimensions
        self._document_count = 0
        self._term_document_frequency = {}
        self._idf = {}

    def _tokenize(self, text):
        import re

        tokens = []
        for word in text.lower().split():
            tokens.extend(re.findall(r"[a-z0-9]+", word))
        return tokens

    def _token_index(self, token):
        import hashlib

        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return int(digest, 16) % self.dimensions

    def fit(self, texts):
        """Learn IDF weights from a corpus of document texts."""
        if isinstance(texts, str):
            texts = [texts]
        self._term_document_frequency = {}
        self._idf = {}
        for text in texts:
            unique = set(self._tokenize(text))
            for token in unique:
                self._term_document_frequency[token] = (
                    self._term_document_frequency.get(token, 0) + 1
                )
            self._document_count += 1

        import math

        for token, df in self._term_document_frequency.items():
            self._idf[token] = math.log(
                1.0 + self._document_count / (1.0 + df)
            )
        return self

    def _text_to_term_counts(self, text):
        counts = {}
        for token in self._tokenize(text):
            counts[token] = counts.get(token, 0) + 1
        return counts

    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token, count in self._text_to_term_counts(text).items():
                index = self._token_index(token)
                vector[index] += count * self._idf.get(token, 1.0)
            norm = sum(v * v for v in vector) ** 0.5
            vectors.append([v / norm if norm else 0.0 for v in vector])
        return vectors