"""Voice-LitE-SQL -- Level 8.1: Schema/Entity Linking.

Identifies likely schema entities (tables, columns) in questions using
exact, normalized, phrase, and fuzzy matching against the database schema.
All schema information comes from L2 Schema Inspector.
"""

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional
import re

from backend.database.schema_inspector import inspect_database, Schema, TableSchema, Column


@dataclass(frozen=True)
class LinkedEntity:
    """A schema entity linked from the question."""
    entity_type: str  # 'table' | 'column'
    table: str
    column: str = ""
    match_type: str = ""  # 'exact' | 'normalized' | 'phrase' | 'fuzzy'
    matched_text: str = ""
    confidence: float = 0.0


@dataclass
class SchemaLinker:
    """Links question tokens to schema entities.

    Parameters
    ----------
    db_path : str
        Path to SQLite database for schema inspection.
    fuzzy_threshold : float
        Minimum similarity ratio for fuzzy matching (0.0-1.0).
    """
    db_path: str
    fuzzy_threshold: float = 0.75

    _schema: Optional[Schema] = field(init=False, default=None)
    _table_map: dict = field(init=False, default_factory=dict)
    _column_map: dict = field(init=False, default_factory=dict)
    _normalized_table_map: dict = field(init=False, default_factory=dict)
    _normalized_column_map: dict = field(init=False, default_factory=dict)

    def __post_init__(self):
        self._load_schema()

    def _load_schema(self):
        """Load and index schema from database."""
        self._schema = inspect_database(self.db_path)

        for table in self._schema.tables:
            norm_table = self._normalize(table.name)
            self._table_map[norm_table] = table.name
            self._normalized_table_map[table.name] = norm_table

            for column in table.columns:
                key = f"{table.name}.{column.name}"
                norm_col = self._normalize(column.name)
                self._column_map[norm_col] = (table.name, column.name)
                self._normalized_column_map[key] = norm_col

    @staticmethod
    def _normalize(text):
        """Normalize text for matching: lowercase, remove non-alnum, collapse spaces."""
        text = text.lower()
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _fuzzy_match(self, query, candidates, threshold=None):
        """Return best fuzzy matches above threshold."""
        threshold = threshold or self.fuzzy_threshold
        matches = []
        for cand in candidates:
            ratio = SequenceMatcher(None, query, cand).ratio()
            if ratio >= threshold:
                matches.append((cand, ratio))
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    def link_tables(self, question):
        """Find table references in question."""
        linked = []
        norm_question = self._normalize(question)
        words = norm_question.split()

        # 1. Exact table name match
        for table in self._schema.tables:
            norm_table = self._normalized_table_map[table.name]
            if norm_table in norm_question:
                linked.append(LinkedEntity(
                    entity_type="table",
                    table=table.name,
                    match_type="exact",
                    matched_text=table.name,
                    confidence=1.0,
                ))

        # 2. Normalized match (singular/plural handling)
        for table in self._schema.tables:
            norm_table = self._normalized_table_map[table.name]
            # Check singular/plural variations
            variations = [norm_table]
            if norm_table.endswith('s'):
                variations.append(norm_table[:-1])
            else:
                variations.append(norm_table + 's')

            for var in variations:
                if var in norm_question and var != norm_table:
                    linked.append(LinkedEntity(
                        entity_type="table",
                        table=table.name,
                        match_type="normalized",
                        matched_text=var,
                        confidence=0.9,
                    ))

        # 3. Fuzzy match on remaining words
        for word in words:
            if len(word) < 3:
                continue
            matches = self._fuzzy_match(word, list(self._table_map.keys()))
            for cand, score in matches[:2]:  # Top 2 fuzzy matches
                table_name = self._table_map[cand]
                # Avoid duplicates
                if not any(e.table == table_name for e in linked):
                    linked.append(LinkedEntity(
                        entity_type="table",
                        table=table_name,
                        match_type="fuzzy",
                        matched_text=word,
                        confidence=round(score, 3),
                    ))

        return linked

    def link_columns(self, question, candidate_tables=None):
        """Find column references in question."""
        linked = []
        norm_question = self._normalize(question)
        words = norm_question.split()

        # Filter columns by candidate tables if provided
        tables_to_search = candidate_tables or [t.name for t in self._schema.tables]
        columns_to_search = []
        for table in self._schema.tables:
            if table.name in tables_to_search:
                for column in table.columns:
                    columns_to_search.append((table.name, column.name))

        # 1. Exact column match (table.column or just column)
        for table_name, col_name in columns_to_search:
            norm_col = self._normalized_column_map[f"{table_name}.{col_name}"]
            full_key = f"{table_name}.{col_name}"

            # Check table.column pattern
            if self._normalize(full_key) in norm_question:
                linked.append(LinkedEntity(
                    entity_type="column",
                    table=table_name,
                    column=col_name,
                    match_type="exact",
                    matched_text=full_key,
                    confidence=1.0,
                ))
            # Check bare column name
            elif norm_col in norm_question:
                linked.append(LinkedEntity(
                    entity_type="column",
                    table=table_name,
                    column=col_name,
                    match_type="exact",
                    matched_text=col_name,
                    confidence=0.95,
                ))

        # 2. Normalized variations (e.g., "employee name" -> employee_name)
        for table_name, col_name in columns_to_search:
            norm_col = self._normalized_column_map[f"{table_name}.{col_name}"]
            # Check spaced version
            spaced = norm_col.replace('_', ' ')
            if spaced in norm_question and spaced != norm_col:
                linked.append(LinkedEntity(
                    entity_type="column",
                    table=table_name,
                    column=col_name,
                    match_type="normalized",
                    matched_text=spaced,
                    confidence=0.85,
                ))

        # 3. Fuzzy match
        for word in words:
            if len(word) < 3:
                continue
            col_candidates = [
                self._normalized_column_map[f"{t}.{c}"]
                for t, c in columns_to_search
            ]
            matches = self._fuzzy_match(word, col_candidates, threshold=0.8)
            for cand, score in matches[:2]:
                # Find original column
                for t, c in columns_to_search:
                    if self._normalized_column_map[f"{t}.{c}"] == cand:
                        if not any(e.table == t and e.column == c for e in linked):
                            linked.append(LinkedEntity(
                                entity_type="column",
                                table=t,
                                column=c,
                                match_type="fuzzy",
                                matched_text=word,
                                confidence=round(score * 0.8, 3),
                            ))
                        break

        return linked

    def link_all(self, question):
        """Link both tables and columns from question."""
        tables = self.link_tables(question)
        columns = self.link_columns(question, candidate_tables=[t.table for t in tables])
        return tables + columns


def link_schema_entities(question, db_path, fuzzy_threshold=0.75):
    """Convenience function to link schema entities from a question."""
    linker = SchemaLinker(db_path, fuzzy_threshold=fuzzy_threshold)
    return linker.link_all(question)