"""Voice-LitE-SQL -- Level 8.1: Phrase/N-gram Matching.

Matches multi-word phrases from questions to schema concepts.
Handles compound column names like "employee name" -> employees.employee_name.
"""

from dataclasses import dataclass
from typing import Optional
import re

from backend.database.schema_inspector import inspect_database, Schema, TableSchema, Column


@dataclass(frozen=True)
class PhraseMatch:
    """A phrase matched to a schema concept."""
    phrase: str
    entity_type: str  # 'table' | 'column' | 'concept'
    table: str
    column: str = ""
    match_type: str = ""  # 'exact' | 'token_overlap' | 'fuzzy'
    score: float = 0.0
    concept: str = ""  # e.g., 'aggregation', 'filter', 'join'


@dataclass
class PhraseMatcher:
    """Matches question phrases to schema concepts.

    Parameters
    ----------
    db_path : str
        Path to SQLite database.
    min_phrase_len : int
        Minimum words in a phrase to consider.
    max_phrase_len : int
        Maximum words in a phrase to consider.
    """
    db_path: str
    min_phrase_len: int = 2
    max_phrase_len: int = 4

    _schema: Optional[Schema] = None
    _column_phrases: dict = None
    _table_phrases: dict = None

    def __post_init__(self):
        self._schema = inspect_database(self.db_path)
        self._build_phrase_index()

    @staticmethod
    def _singularize(word):
        """Simple singularization for common cases."""
        # Handle specific irregular plurals first
        irregular = {
            'names': 'name',
            'ids': 'id',
            'categories': 'category',
            'cities': 'city',
            'regions': 'region',
            'employees': 'employee',
            'departments': 'department',
            'products': 'product',
            'customers': 'customer',
            'sales': 'sale',
            'orders': 'order',
            'locations': 'location',
        }
        if word in irregular:
            return irregular[word]
        # General rules
        if word.endswith('ies'):
            return word[:-3] + 'y'
        elif word.endswith('es') and len(word) > 3:
            # words like 'names' -> 'name', but not 'es' -> ''
            return word[:-2] if word[:-2] else word
        elif word.endswith('s') and not word.endswith('ss') and len(word) > 2:
            return word[:-1]
        return word

    def _build_phrase_index(self):
        """Build searchable phrases from schema."""
        self._column_phrases = {}
        self._table_phrases = {}

        for table in self._schema.tables:
            # Table phrases
            table_phrase = table.name.replace('_', ' ').lower()
            self._table_phrases[table_phrase] = table.name
            # Add singular/plural variants
            words = table_phrase.split()
            for i, w in enumerate(words):
                sing = self._singularize(w)
                if sing != w:
                    variant = ' '.join(words[:i] + [sing] + words[i+1:])
                    self._table_phrases[variant] = table.name

            # Column phrases
            for column in table.columns:
                col_phrase = column.name.replace('_', ' ').lower()
                key = f"{table.name}.{column.name}"
                self._column_phrases[col_phrase] = (table.name, column.name)

                # Add singular/plural variants for column phrases
                words = col_phrase.split()
                for i, w in enumerate(words):
                    sing = self._singularize(w)
                    if sing != w:
                        variant = ' '.join(words[:i] + [sing] + words[i+1:])
                        self._column_phrases[variant] = (table.name, column.name)

                # Also add table.column phrase
                full_phrase = f"{table_phrase} {col_phrase}"
                self._column_phrases[full_phrase] = (table.name, column.name)

    def _extract_phrases(self, text):
        """Extract n-gram phrases from text, including singular variants."""
        words = re.findall(r'\b\w+\b', text.lower())
        phrases = []
        for length in range(self.min_phrase_len, self.max_phrase_len + 1):
            for i in range(len(words) - length + 1):
                phrase = ' '.join(words[i:i + length])
                phrases.append(phrase)
                # Also add singular variants
                sing_words = [self._singularize(w) for w in words[i:i + length]]
                sing_phrase = ' '.join(sing_words)
                if sing_phrase != phrase:
                    phrases.append(sing_phrase)
        return phrases

    def _token_overlap_score(self, phrase1, phrase2):
        """Compute token overlap score between two phrases."""
        tokens1 = set(phrase1.split())
        tokens2 = set(phrase2.split())
        if not tokens1 or not tokens2:
            return 0.0
        intersection = tokens1 & tokens2
        union = tokens1 | tokens2
        return len(intersection) / len(union)

    def match_phrases(self, question):
        """Match question phrases to schema concepts."""
        matches = []
        phrases = self._extract_phrases(question)
        question_lower = question.lower()

        # 1. Exact phrase matches
        for phrase in phrases:
            # Check columns
            for col_phrase, (table, column) in self._column_phrases.items():
                if phrase == col_phrase:
                    matches.append(PhraseMatch(
                        phrase=phrase,
                        entity_type="column",
                        table=table,
                        column=column,
                        match_type="exact",
                        score=1.0,
                    ))

            # Check tables
            for table_phrase, table in self._table_phrases.items():
                if phrase == table_phrase:
                    matches.append(PhraseMatch(
                        phrase=phrase,
                        entity_type="table",
                        table=table,
                        match_type="exact",
                        score=1.0,
                    ))

        # 2. Token overlap matches (for partial matches)
        for phrase in phrases:
            # Columns
            for col_phrase, (table, column) in self._column_phrases.items():
                if phrase != col_phrase:
                    score = self._token_overlap_score(phrase, col_phrase)
                    if score >= 0.5:  # At least 50% token overlap
                        matches.append(PhraseMatch(
                            phrase=phrase,
                            entity_type="column",
                            table=table,
                            column=column,
                            match_type="token_overlap",
                            score=round(score, 3),
                        ))

            # Tables
            for table_phrase, table in self._table_phrases.items():
                if phrase != table_phrase:
                    score = self._token_overlap_score(phrase, table_phrase)
                    if score >= 0.5:
                        matches.append(PhraseMatch(
                            phrase=phrase,
                            entity_type="table",
                            table=table,
                            match_type="token_overlap",
                            score=round(score, 3),
                        ))

        # 3. Concept phrases (aggregation, filter, etc.)
        concept_patterns = {
            "average": ("aggregation", "AVG"),
            "mean": ("aggregation", "AVG"),
            "sum": ("aggregation", "SUM"),
            "total": ("aggregation", "SUM"),
            "count": ("aggregation", "COUNT"),
            "how many": ("aggregation", "COUNT"),
            "maximum": ("aggregation", "MAX"),
            "max": ("aggregation", "MAX"),
            "highest": ("aggregation", "MAX"),
            "minimum": ("aggregation", "MIN"),
            "min": ("aggregation", "MIN"),
            "lowest": ("aggregation", "MIN"),
            "group by": ("grouping", "GROUP BY"),
            "per": ("grouping", "GROUP BY"),
            "each": ("grouping", "GROUP BY"),
            "order by": ("ordering", "ORDER BY"),
            "sort by": ("ordering", "ORDER BY"),
            "sorted by": ("ordering", "ORDER BY"),
            "top": ("ordering", "ORDER BY ... LIMIT"),
            "bottom": ("ordering", "ORDER BY ... LIMIT"),
            "most recent": ("ordering", "ORDER BY ... DESC"),
            "latest": ("ordering", "ORDER BY ... DESC"),
            "earliest": ("ordering", "ORDER BY ... ASC"),
        }

        for concept_phrase, (concept_type, sql_hint) in concept_patterns.items():
            if concept_phrase in question_lower:
                matches.append(PhraseMatch(
                    phrase=concept_phrase,
                    entity_type="concept",
                    table="",
                    column="",
                    match_type="concept",
                    score=1.0,
                    concept=f"{concept_type}:{sql_hint}",
                ))

        # Deduplicate by (phrase, entity_type, table, column)
        seen = set()
        unique = []
        for m in matches:
            key = (m.phrase, m.entity_type, m.table, m.column)
            if key not in seen:
                seen.add(key)
                unique.append(m)

        # Sort by score descending
        unique.sort(key=lambda x: x.score, reverse=True)
        return unique


def match_phrases(question, db_path, min_phrase_len=2, max_phrase_len=4):
    """Convenience function to match phrases."""
    matcher = PhraseMatcher(db_path, min_phrase_len, max_phrase_len)
    return matcher.match_phrases(question)