
"""Voice-LitE-SQL -- Level 8.1: Candidate Reranking.

Lightweight reranking of retrieved schema documents combining:
- Vector similarity (from ChromaDB)
- Lexical similarity
- Phrase similarity
- Table/column relevance
- Query intent compatibility
- Relationship necessity

Weights are configurable and documented.
"""

from dataclasses import dataclass, field
from typing import Optional
import re

from backend.retrieval.schema_retriever import RetrievedItem, RetrievalResult
from backend.nlp.intent_classifier import IntentResult, QueryIntent
from backend.nlp.schema_linker import LinkedEntity
from backend.nlp.phrase_matcher import PhraseMatch


@dataclass(frozen=True)
class RerankWeights:
    """Configurable weights for reranking components.

    All weights should sum to 1.0 for interpretability.
    Default values based on empirical analysis of L7 failure modes.
    """
    vector_similarity: float = 0.30      # Original ChromaDB score
    lexical_overlap: float = 0.20        # Token overlap with question
    phrase_match: float = 0.20           # Phrase matcher score
    intent_compatibility: float = 0.15   # Intent alignment
    table_relevance: float = 0.10        # Table directly referenced
    column_relevance: float = 0.05       # Column directly referenced

    def __post_init__(self):
        total = (self.vector_similarity + self.lexical_overlap +
                 self.phrase_match + self.intent_compatibility +
                 self.table_relevance + self.column_relevance)
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Weights must sum to 1.0, got {total}")


@dataclass
class Reranker:
    """Reranks retrieved schema items using multiple signals.

    Parameters
    ----------
    weights : RerankWeights
        Weight configuration for reranking signals.
    """
    weights: RerankWeights = field(default_factory=RerankWeights)

    def _lexical_overlap(self, question, item_text):
        """Compute token overlap between question and item."""
        q_tokens = set(re.findall(r'\b\w+\b', question.lower()))
        i_tokens = set(re.findall(r'\b\w+\b', item_text.lower()))
        if not q_tokens or not i_tokens:
            return 0.0
        return len(q_tokens & i_tokens) / len(q_tokens | i_tokens)

    def _phrase_match_score(self, item, phrase_matches):
        """Get best phrase match score for this item."""
        best = 0.0
        for pm in phrase_matches:
            if pm.entity_type == "column" and pm.table == item.table and pm.column == item.column:
                best = max(best, pm.score)
            elif pm.entity_type == "table" and pm.table == item.table:
                best = max(best, pm.score)
            elif pm.entity_type == "concept":
                # Concept matches apply broadly
                best = max(best, pm.score * 0.5)
        return best

    def _intent_compatibility(self, item, intent):
        """Score how well item matches the query intent."""
        if intent.primary_intent == QueryIntent.SELECT:
            # For SELECT, prefer columns and tables, not relationships
            if item.doc_type == "column":
                return 1.0
            elif item.doc_type == "table":
                return 0.8
            elif item.doc_type == "relationship":
                return 0.2  # Relationships not needed for simple SELECT

        elif intent.primary_intent == QueryIntent.WHERE:
            # For WHERE, columns (filters) and tables are important
            if item.doc_type == "column":
                return 1.0
            elif item.doc_type == "table":
                return 0.7
            elif item.doc_type == "relationship":
                return 0.3

        elif intent.primary_intent == QueryIntent.JOIN:
            # For JOIN, relationships are critical
            if item.doc_type == "relationship":
                return 1.0
            elif item.doc_type == "column":
                return 0.7
            elif item.doc_type == "table":
                return 0.6

        elif intent.primary_intent in (QueryIntent.GROUP_BY, QueryIntent.AGGREGATE, QueryIntent.COMPLEX):
            # For complex queries, need columns, tables, and relationships
            if item.doc_type == "column":
                return 0.9
            elif item.doc_type == "relationship":
                return 0.8
            elif item.doc_type == "table":
                return 0.7

        elif intent.primary_intent == QueryIntent.ORDER_BY:
            if item.doc_type == "column":
                return 1.0
            elif item.doc_type == "table":
                return 0.6
            elif item.doc_type == "relationship":
                return 0.3

        return 0.5

    def _table_relevance(self, item, linked_entities):
        """Score if this item's table was explicitly linked."""
        for le in linked_entities:
            if le.entity_type == "table" and le.table == item.table:
                return le.confidence
            if le.entity_type == "column" and le.table == item.table:
                return le.confidence * 0.8
        return 0.0

    def _column_relevance(self, item, linked_entities):
        """Score if this item's column was explicitly linked."""
        if item.doc_type != "column":
            return 0.0
        for le in linked_entities:
            if le.entity_type == "column" and le.table == item.table and le.column == item.column:
                return le.confidence
        return 0.0

    def rerank(self, question, retrieval, intent, linked_entities, phrase_matches):
        """Rerank retrieved items using all signals.

        Parameters
        ----------
        question : str
            Original question.
        retrieval : RetrievalResult
            Original retrieval result.
        intent : IntentResult
            Query intent classification.
        linked_entities : list[LinkedEntity]
            Schema-linked entities from question.
        phrase_matches : list[PhraseMatch]
            Phrase matches from question.

        Returns
        -------
        RetrievalResult
            New retrieval result with reranked items.
        """
        scored_items = []

        for item in retrieval.items:
            # Vector score (normalized from distance)
            vector_score = 1.0 - item.distance if item.distance <= 1.0 else 0.0

            # Lexical overlap
            lex_score = self._lexical_overlap(question, item.text)

            # Phrase match
            phrase_score = self._phrase_match_score(item, phrase_matches)

            # Intent compatibility
            intent_score = self._intent_compatibility(item, intent)

            # Table relevance
            table_score = self._table_relevance(item, linked_entities)

            # Column relevance
            column_score = self._column_relevance(item, linked_entities)

            # Combined weighted score
            final_score = (
                self.weights.vector_similarity * vector_score +
                self.weights.lexical_overlap * lex_score +
                self.weights.phrase_match * phrase_score +
                self.weights.intent_compatibility * intent_score +
                self.weights.table_relevance * table_score +
                self.weights.column_relevance * column_score
            )

            scored_items.append((item, round(final_score, 4)))

        # Sort by score descending, stable sort for ties
        scored_items.sort(key=lambda x: x[1], reverse=True)

        # Create new items with updated scores
        reranked_items = []
        for item, score in scored_items:
            new_item = RetrievedItem(
                doc_type=item.doc_type,
                doc_id=item.doc_id,
                table=item.table,
                column=item.column,
                fk_source_table=item.fk_source_table,
                fk_source_column=item.fk_source_column,
                fk_target_table=item.fk_target_table,
                fk_target_column=item.fk_target_column,
                text=item.text,
                score=score,
                distance=1.0 - score if score <= 1.0 else 0.0,
                source=item.source,
            )
            reranked_items.append(new_item)

        return RetrievalResult(
            question=retrieval.question,
            top_k=retrieval.top_k,
            items=reranked_items,
            schema_context_text="",  # Will be regenerated
        )


def rerank_retrieval(question, retrieval, intent, linked_entities, phrase_matches, weights=None):
    """Convenience function to rerank retrieval results."""
    reranker = Reranker(weights or RerankWeights())
    return reranker.rerank(question, retrieval, intent, linked_entities, phrase_matches)