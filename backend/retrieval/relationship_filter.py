"""Voice-LitE-SQL -- Level 8.1: Relationship Necessity Filter.

Distinguishes between:
- Relationship EXISTS (FK in schema)
- Relationship REQUIRED (needed to answer the question)

This is the core fix for the L7 failure mode where available FKs
are incorrectly assumed to require JOINs.
"""

from dataclasses import dataclass, field
from typing import Optional
import re

from backend.retrieval.schema_retriever import RetrievedItem, RetrievalResult
from backend.nlp.intent_classifier import IntentResult, QueryIntent
from backend.nlp.schema_linker import LinkedEntity
from backend.database.schema_inspector import inspect_database, ForeignKey


@dataclass(frozen=True)
class RelationshipAssessment:
    """Assessment of whether a relationship is required."""
    fk_source_table: str
    fk_source_column: str
    fk_target_table: str
    fk_target_column: str
    required: bool
    reason: str
    confidence: float


@dataclass
class RelationshipFilter:
    """Filters relationships based on query intent and question semantics.

    Parameters
    ----------
    db_path : str
        Path to SQLite database for full schema access.
    """
    db_path: str

    _schema: Optional[object] = field(init=False, default=None)
    _fk_map: dict = field(init=False, default_factory=dict)

    def __post_init__(self):
        self._load_schema()

    def _load_schema(self):
        """Load schema and build FK lookup map."""
        self._schema = inspect_database(self.db_path)

        # Build bidirectional FK map: (source_table, source_col) -> (target_table, target_col)
        for table in self._schema.tables:
            for fk in table.foreign_keys:
                key = (table.name, fk.source_column)
                self._fk_map[key] = (fk.target_table, fk.target_column)

                # Also add reverse lookup
                rev_key = (fk.target_table, fk.target_column)
                if rev_key not in self._fk_map:
                    self._fk_map[rev_key] = (table.name, fk.source_column)

    def _tables_in_question(self, question, linked_entities):
        """Extract explicitly mentioned tables from question and linking."""
        tables = set()
        question_lower = question.lower()

        # From linked entities
        for le in linked_entities:
            if le.entity_type == "table":
                tables.add(le.table)
            elif le.entity_type == "column":
                tables.add(le.table)

        # Direct table name mentions
        for table in self._schema.tables:
            if table.name.lower() in question_lower:
                tables.add(table.name)
            # Check plural/singular
            norm = table.name.lower().replace('_', ' ')
            if norm in question_lower:
                tables.add(table.name)
            if norm.endswith('s'):
                singular = norm[:-1]
                if singular in question_lower:
                    tables.add(table.name)
            else:
                plural = norm + 's'
                if plural in question_lower:
                    tables.add(table.name)

        return tables

    def _columns_in_question(self, question, linked_entities):
        """Extract explicitly mentioned columns."""
        columns = set()
        for le in linked_entities:
            if le.entity_type == "column":
                columns.add((le.table, le.column))
        return columns

    def _assess_relationship(self, item, question, intent, linked_entities, mentioned_tables, mentioned_columns):
        """Assess if a relationship document is required."""
        src_table = item.fk_source_table
        src_col = item.fk_source_column
        tgt_table = item.fk_target_table
        tgt_col = item.fk_target_column

        # Check if both tables are mentioned
        src_mentioned = src_table in mentioned_tables
        tgt_mentioned = tgt_table in mentioned_tables

        # Check if join column is explicitly mentioned
        src_col_mentioned = (src_table, src_col) in mentioned_columns
        tgt_col_mentioned = (tgt_table, tgt_col) in mentioned_columns

        # Intent-based rules
        if intent.primary_intent == QueryIntent.SELECT:
            # Simple SELECT: relationship ONLY required if question explicitly
            # references columns from BOTH tables
            if src_mentioned and tgt_mentioned and (src_col_mentioned or tgt_col_mentioned):
                return RelationshipAssessment(
                    fk_source_table=src_table,
                    fk_source_column=src_col,
                    fk_target_table=tgt_table,
                    fk_target_column=tgt_col,
                    required=True,
                    reason="SELECT with explicit columns from both tables",
                    confidence=0.9,
                )
            # Also check for phrases like "with", "along with"
            join_words = ["with", "along with", "together with", "and"]
            if any(w in question.lower() for w in join_words) and src_mentioned and tgt_mentioned:
                return RelationshipAssessment(
                    fk_source_table=src_table,
                    fk_source_column=src_col,
                    fk_target_table=tgt_table,
                    fk_target_column=tgt_col,
                    required=True,
                    reason="SELECT with join-indicating phrase",
                    confidence=0.7,
                )
            return RelationshipAssessment(
                fk_source_table=src_table,
                fk_source_column=src_col,
                fk_target_table=tgt_table,
                fk_target_column=tgt_col,
                required=False,
                reason="Simple SELECT: no JOIN needed unless both tables explicitly required",
                confidence=0.8,
            )

        elif intent.primary_intent == QueryIntent.WHERE:
            # WHERE: need JOIN if filter references column from another table
            if src_mentioned and tgt_mentioned:
                if src_col_mentioned or tgt_col_mentioned:
                    return RelationshipAssessment(
                        fk_source_table=src_table,
                        fk_source_column=src_col,
                        fk_target_table=tgt_table,
                        fk_target_column=tgt_col,
                        required=True,
                        reason="WHERE clause references columns from both tables",
                        confidence=0.85,
                    )
            return RelationshipAssessment(
                fk_source_table=src_table,
                fk_source_column=src_col,
                fk_target_table=tgt_table,
                fk_target_column=tgt_col,
                required=False,
                reason="WHERE on single table: no JOIN needed",
                confidence=0.75,
            )

        elif intent.primary_intent == QueryIntent.JOIN:
            # JOIN intent: relationship likely required
            if src_mentioned and tgt_mentioned:
                return RelationshipAssessment(
                    fk_source_table=src_table,
                    fk_source_column=src_col,
                    fk_target_table=tgt_table,
                    fk_target_column=tgt_col,
                    required=True,
                    reason="JOIN intent with both tables mentioned",
                    confidence=0.95,
                )
            # Check if question implies connection between two entities
            return RelationshipAssessment(
                fk_source_table=src_table,
                fk_source_column=src_col,
                fk_target_table=tgt_table,
                fk_target_column=tgt_col,
                required=src_mentioned or tgt_mentioned,
                reason="JOIN intent: relationship needed if tables connected to question",
                confidence=0.7,
            )

        elif intent.primary_intent in (QueryIntent.GROUP_BY, QueryIntent.AGGREGATE, QueryIntent.COMPLEX):
            # Complex queries: often need relationships for grouping/aggregation across tables
            if src_mentioned and tgt_mentioned:
                return RelationshipAssessment(
                    fk_source_table=src_table,
                    fk_source_column=src_col,
                    fk_target_table=tgt_table,
                    fk_target_column=tgt_col,
                    required=True,
                    reason="Complex query with both tables referenced",
                    confidence=0.9,
                )
            # If grouping/aggregation mentions columns from both sides
            if (src_col_mentioned and tgt_mentioned) or (tgt_col_mentioned and src_mentioned):
                return RelationshipAssessment(
                    fk_source_table=src_table,
                    fk_source_column=src_col,
                    fk_target_table=tgt_table,
                    fk_target_column=tgt_col,
                    required=True,
                    reason="Aggregation/GROUP BY spans both tables",
                    confidence=0.85,
                )
            return RelationshipAssessment(
                fk_source_table=src_table,
                fk_source_column=src_col,
                fk_target_table=tgt_table,
                fk_target_column=tgt_col,
                required=False,
                reason="Complex query but single table sufficient",
                confidence=0.6,
            )

        elif intent.primary_intent == QueryIntent.ORDER_BY:
            # ORDER BY: similar to SELECT
            if src_mentioned and tgt_mentioned and (src_col_mentioned or tgt_col_mentioned):
                return RelationshipAssessment(
                    fk_source_table=src_table,
                    fk_source_column=src_col,
                    fk_target_table=tgt_table,
                    fk_target_column=tgt_col,
                    required=True,
                    reason="ORDER BY with columns from both tables",
                    confidence=0.8,
                )
            return RelationshipAssessment(
                fk_source_table=src_table,
                fk_source_column=src_col,
                fk_target_table=tgt_table,
                fk_target_column=tgt_col,
                required=False,
                reason="ORDER BY on single table",
                confidence=0.7,
            )

        return RelationshipAssessment(
            fk_source_table=src_table,
            fk_source_column=src_col,
            fk_target_table=tgt_table,
            fk_target_column=tgt_col,
            required=False,
            reason="Default: relationship not required",
            confidence=0.5,
        )

    def filter_relationships(self, question, retrieval, intent, linked_entities):
        """Filter retrieval items, keeping only necessary relationships.

        Parameters
        ----------
        question : str
            Original question.
        retrieval : RetrievalResult
            Retrieval result with items including relationships.
        intent : IntentResult
            Query intent classification.
        linked_entities : list[LinkedEntity]
            Schema-linked entities.

        Returns
        -------
        RetrievalResult
            Filtered retrieval with only necessary relationships.
        """
        mentioned_tables = self._tables_in_question(question, linked_entities)
        mentioned_columns = self._columns_in_question(question, linked_entities)

        filtered_items = []
        relationship_assessments = []

        for item in retrieval.items:
            if item.doc_type == "relationship":
                assessment = self._assess_relationship(
                    item, question, intent, linked_entities,
                    mentioned_tables, mentioned_columns
                )
                relationship_assessments.append(assessment)
                if assessment.required:
                    filtered_items.append(item)
                # Non-required relationships are dropped
            elif item.doc_type == "column":
                # Check if this column's table is required
                table = item.table
                table_required = False
                for rel in relationship_assessments:
                    if rel.required and (rel.fk_source_table == table or rel.fk_target_table == table):
                        table_required = True
                        break
                # Also keep if table is explicitly mentioned in question
                if table in mentioned_tables:
                    table_required = True
                # Also keep if column is explicitly mentioned
                if (item.table, item.column) in mentioned_columns:
                    table_required = True
                if table_required:
                    filtered_items.append(item)
            else:
                # Always keep tables
                filtered_items.append(item)

        # Ensure columns referenced by kept relationships are also present
        kept_relationships = [a for a in relationship_assessments if a.required]
        required_columns = set()
        for rel in kept_relationships:
            required_columns.add((rel.fk_source_table, rel.fk_source_column))
            required_columns.add((rel.fk_target_table, rel.fk_target_column))

        # Add missing required columns
        existing_columns = {(item.table, item.column) for item in filtered_items if item.doc_type == "column"}
        for table, column in required_columns:
            if (table, column) not in existing_columns:
                # Find the column document
                for item in retrieval.items:
                    if item.doc_type == "column" and item.table == table and item.column == column:
                        filtered_items.append(item)
                        break

        return RetrievalResult(
            question=retrieval.question,
            top_k=retrieval.top_k,
            items=filtered_items,
            schema_context_text="",
        ), relationship_assessments


def filter_relationships(question, retrieval, intent, linked_entities, db_path):
    """Convenience function to filter relationships."""
    filter_obj = RelationshipFilter(db_path)
    return filter_obj.filter_relationships(question, retrieval, intent, linked_entities)