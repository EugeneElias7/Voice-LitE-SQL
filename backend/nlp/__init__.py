"""Voice-LitE-SQL -- Level 8.1: NLP + Schema-Linking Optimization.

Lightweight NLP components for query intent classification, schema/entity
linking, phrase matching, and relationship necessity filtering.
All components are deterministic and work with the 1.5B model.
"""

from backend.nlp.intent_classifier import QueryIntent, classify_intent
from backend.nlp.schema_linker import SchemaLinker, link_schema_entities
from backend.nlp.phrase_matcher import PhraseMatcher, match_phrases

__all__ = [
    "QueryIntent",
    "classify_intent",
    "SchemaLinker",
    "link_schema_entities",
    "PhraseMatcher",
    "match_phrases",
]