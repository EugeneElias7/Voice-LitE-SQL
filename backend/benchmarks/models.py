"""Voice-LitE-SQL -- Level 10: common external-benchmark data model.

A benchmark-agnostic representation of one text-to-SQL question plus the
resolved path to the target SQLite database. Loaders for individual
benchmarks (Spider, BIRD) normalize their native records into this structure.

No Enterprise-specific tables or columns are referenced anywhere in this
package: everything is driven by the external dataset itself.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class BenchmarkQuestion:
    """One external text-to-SQL question in normalized form.

    Attributes
    ----------
    question:
        the natural-language question text.
    database_id:
        identifier of the target database inside the benchmark (e.g. a
        Spider ``db_id`` or a BIRD ``db_id``).
    database_path:
        resolved absolute path to the target SQLite file (None if the file
        is missing for this database id).
    reference_sql:
        the gold/reference SQL for this question, if the split provides it
        (None for hidden splits, e.g. a test set without released gold).
    split:
        which benchmark split it came from (e.g. "train", "dev", "test").
    evidence:
        optional free-form evidence/hint text (BIRD provides it; Spider
        generally does not).
    metadata:
        any additional benchmark-specific fields (difficulty, question id,
        native record fields, ...).
    """

    question: str
    database_id: str
    database_path: Optional[str] = None
    reference_sql: Optional[str] = None
    split: str = "dev"
    evidence: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        """JSON-serializable representation (used for reports)."""
        return {
            "question": self.question,
            "database_id": self.database_id,
            "database_path": self.database_path,
            "reference_sql": self.reference_sql,
            "split": self.split,
            "evidence": self.evidence,
            "metadata": self.metadata,
        }


@dataclass
class BenchmarkDatabase:
    """One discovered external SQLite database.

    Attributes
    ----------
    database_id:
        benchmark identifier of the database.
    path:
        resolved absolute path to the SQLite file (None if missing).
    split:
        which split the database was discovered in (e.g. "database" vs
        "test_database" for Spider).
    """

    database_id: str
    path: Optional[str] = None
    split: str = ""

    def to_dict(self):
        return {
            "database_id": self.database_id,
            "path": self.path,
            "split": self.split,
        }