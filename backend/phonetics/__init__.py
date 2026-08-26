"""Voice-LitE-SQL -- Level 6: database-aware phonetic normalization."""

from backend.phonetics.algorithms import (
    ALGORITHMS,
    best_similarity,
    clean_token,
    is_number,
    phonetic_key,
    phonetic_matches,
    similarity,
)
from backend.phonetics.normalizer import (
    Correction,
    DatabaseAwareNormalizer,
    NormalizationResult,
    NormalizerConfig,
    TokenDecision,
)
from backend.phonetics.vocabulary import DatabaseVocabulary, VocabTerm

__all__ = [
    "ALGORITHMS",
    "Correction",
    "DatabaseAwareNormalizer",
    "DatabaseVocabulary",
    "NormalizationResult",
    "NormalizerConfig",
    "TokenDecision",
    "VocabTerm",
    "best_similarity",
    "clean_token",
    "is_number",
    "phonetic_key",
    "phonetic_matches",
    "similarity",
]
