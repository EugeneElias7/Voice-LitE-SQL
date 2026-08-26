"""Voice-LitE-SQL -- Level 6: database-aware vocabulary.

Builds the candidate vocabulary from the schema of the database being
queried: table names, column names, and the words of multi-word columns
(e.g. ``sale_date`` contributes ``sale`` and ``date``, each linked back to
its parent column).
"""

import json
from dataclasses import dataclass

KIND_PRIORITY = {"table": 3, "column": 2, "word": 1}


@dataclass(frozen=True)
class VocabTerm:
    term: str
    kind: str  # "table" | "column" | "word"
    parent: str = None  # parent column for kind == "word"


class DatabaseVocabulary:
    """Schema-grounded vocabulary with lookup helpers for the normalizer."""

    def __init__(self, terms):
        self.terms = sorted(terms, key=lambda t: KIND_PRIORITY[t.kind], reverse=True)
        self._by_term = {}
        for term in self.terms:
            existing = self._by_term.get(term.term)
            if existing is None or KIND_PRIORITY[term.kind] > KIND_PRIORITY[existing.kind]:
                self._by_term[term.term] = term
        self._resolve_ambiguous_words()
        self._multiword = [
            (column, tuple(column.split("_")))
            for column, kind in ((t.term, t.kind) for t in self._by_term.values())
            if kind == "column" and "_" in column
        ]

    def _resolve_ambiguous_words(self):
        """A word shared by several columns ('name', 'customer', 'sale') is
        not uniquely grounded; its ``parent`` is cleared so corrections
        report ambiguity instead of a misleading single column."""
        parent_counts = {}
        for term in self.terms:
            if term.kind == "word" and term.parent:
                parents = parent_counts.setdefault(term.term, set())
                parents.add(term.parent)
        for term in self._by_term.values():
            if term.kind == "word" and len(parent_counts.get(term.term, ())) > 1:
                term = VocabTerm(term.term, term.kind, parent=None)
                self._by_term[term.term] = term

    @classmethod
    def from_schema(cls, schema):
        """Build from a schema mapping ``{table: {"columns": [...]}}``."""
        terms = []
        for table, info in schema.items():
            terms.append(VocabTerm(table, "table"))
            for column in info.get("columns", []):
                terms.append(VocabTerm(column, "column"))
                for word in column.split("_"):
                    if len(word) >= 3 and word != column:
                        terms.append(VocabTerm(word, "word", parent=column))
        return cls(terms)

    @classmethod
    def from_schema_json(cls, path):
        with open(path, encoding="utf-8") as handle:
            return cls.from_schema(json.load(handle))

    @classmethod
    def from_database(cls, db_path):
        """Build the vocabulary from any SQLite database via the L2 Schema
        Inspector (never hardcoded, never from models.py)."""
        from backend.database.schema_inspector import inspect_database

        schema = inspect_database(db_path)
        return cls.from_schema(
            {
                table.name: {"columns": [column.name for column in table.columns]}
                for table in schema.tables
            }
        )

    @property
    def candidates(self):
        """All unique candidate strings (tables, columns, words)."""
        return list(self._by_term)

    @property
    def multiword_spans(self):
        """List of ``(canonical_column, word_sequence)`` for merge passes."""
        return sorted(self._multiword, key=lambda item: -len(item[1]))

    def kind_of(self, term):
        found = self._by_term.get(term)
        return found.kind if found else None

    def parent_of(self, term):
        found = self._by_term.get(term)
        return found.parent if found else None

    def lookup(self, term):
        return self._by_term.get(term)
