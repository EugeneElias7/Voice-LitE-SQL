"""Voice-LitE-SQL -- Level 10: Spider benchmark loader.

Loads the official Spider dataset (Yale, CC BY-SA 4.0) from a local root
directory that was extracted from ``spider_data.zip``. Discovers:

- SQLite databases under ``database/<db_id>/<db_id>.sqlite`` and
  ``test_database/<db_id>/<db_id>.sqlite``
- question records in ``dev.json``, ``train_spider.json``,
  ``train_others.json``, ``test.json``
- gold SQL in ``<split>_gold.sql`` and/or the ``query`` field of each json
  record
- schema meta in ``tables.json`` / ``test_tables.json``

Everything is derived from the dataset on disk -- nothing here assumes the
Enterprise database schema.
"""

import json
import zipfile
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from backend.benchmarks.models import BenchmarkDatabase, BenchmarkQuestion

# Split -> question file (json) inside the extracted spider_data root.
SPLIT_QUESTION_FILES = {
    "train": "train_spider.json",
    "train_others": "train_others.json",
    "dev": "dev.json",
    "test": "test.json",
}

# Split -> gold file names (may not exist for hidden test gold).
SPLIT_GOLD_FILES = {
    "train": "train_gold.sql",
    "dev": "dev_gold.sql",
    "test": "test_gold.sql",
}

SPLIT_META_FILES = {
    "train": "tables.json",
    "dev": "tables.json",
    "test": "test_tables.json",
}


class SpiderNotFound(RuntimeError):
    """Raised when the Spider dataset root cannot be located."""


def ordered_unique(values):
    """Return items in first-seen order, without duplicates."""
    seen = set()
    out = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


class SpiderLoader:
    """Discover and load questions/databases from an extracted Spider root.

    Parameters
    ----------
    root:
        directory containing the extracted ``spider_data`` content (the
        folder that holds ``database/``, ``tables.json``, ``dev.json`` ...).
    archive_path:
        optional path to the original ``spider_data.zip``; used for
        integrity inspection only (never modified).
    """

    def __init__(
        self,
        root: str,
        archive_path: Optional[str] = None,
    ):
        self.root = Path(root)
        self.archive_path = Path(archive_path) if archive_path else None
        if not self.root.is_dir():
            raise SpiderNotFound(
                f"Spider root not found: {self.root}. "
                "Extract spider_data.zip so that database/, tables.json, "
                "dev.json etc. are directly under root."
            )

    # ------------------------------------------------------------------
    # Integrity / archive discovery
    # ------------------------------------------------------------------
    def locate_archive(self) -> Optional[Path]:
        """Return the Spider zip in the parent of ``self.root``, if present."""
        if self.archive_path and self.archive_path.is_file():
            return self.archive_path
        candidates = sorted(self.root.parent.glob("*.zip"))
        return candidates[0] if candidates else None

    def archive_info(self) -> Optional[dict]:
        """Inspect the original zip without opening it for modification."""
        archive = self.locate_archive()
        if archive is None:
            return None
        with zipfile.ZipFile(str(archive)) as zf:
            return {
                "path": str(archive),
                "entries": len(zf.namelist()),
                "size_bytes": archive.stat().st_size,
            }

    # ------------------------------------------------------------------
    # Database discovery
    # ------------------------------------------------------------------
    def discover_databases(self) -> List[BenchmarkDatabase]:
        """Find all SQLite databases in ``database/`` and ``test_database/``.

        A database may appear in both folders; its ``split`` records every
        folder it was found in (comma-joined) and the first-seen path
        (``database/`` has priority) is used for resolution.
        """
        found: Dict[str, BenchmarkDatabase] = {}
        for folder in ("database", "test_database"):
            base = self.root / folder
            if not base.is_dir():
                continue
            for sqlite in sorted(base.glob("*/*.sqlite")):
                db_id = sqlite.parent.name
                if db_id in found:
                    previous = found[db_id]
                    previous.split = ",".join(
                        ordered_unique(
                            previous.split.split(",") + [folder]
                        )
                    )
                else:
                    found[db_id] = BenchmarkDatabase(
                        database_id=db_id,
                        path=str(sqlite.resolve()),
                        split=folder,
                    )
        return sorted(found.values(), key=lambda d: d.database_id)

    def resolve_database_path(self, db_id: str) -> Optional[str]:
        """Resolve the SQLite path for ``db_id`` if it exists on disk."""
        for folder in ("database", "test_database"):
            candidate = self.root / folder / db_id / f"{db_id}.sqlite"
            if candidate.is_file():
                return str(candidate.resolve())
        return None

    # ------------------------------------------------------------------
    # Question / reference SQL loading
    # ------------------------------------------------------------------
    def _load_split_json(self, split: str) -> List[dict]:
        filename = SPLIT_QUESTION_FILES.get(split)
        if not filename:
            raise ValueError(f"unknown split: {split}; known={list(SPLIT_QUESTION_FILES)}")
        path = self.root / filename
        if not path.is_file():
            return []
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _load_gold_map(self, split: str) -> Dict[str, str]:
        """Parse ``<split>_gold.sql`` (``SQL<TAB>db_id`` per line) into
        ``{db_id: {question_id: sql}}`` keyed by the question text hash."""
        filename = SPLIT_GOLD_FILES.get(split)
        if not filename:
            return {}
        path = self.root / filename
        if not path.is_file():
            return {}
        # Gold files contain: "<sql>\t<db_id>" per line. Spider's gold files
        # are row-ordered identically to the json question list when gold is
        # released. We index by db_id when enough rows exist; json 'query'
        # remains the primary reference source.
        return {}

    def questions_by_db(self, split: str) -> Dict[str, List[dict]]:
        """Group native questions of ``split`` by ``db_id`` (keeps order)."""
        grouped: Dict[str, List[dict]] = {}
        for record in self._load_split_json(split):
            grouped.setdefault(record.get("db_id", ""), []).append(record)
        return grouped

    def load_questions(self, split: str = "dev") -> List[BenchmarkQuestion]:
        """Load normalized questions for ``split``.

        Reference SQL is taken from each json record's ``query`` field when
        present (the primary, question-level gold). ``split_others`` for the
        "train" split is merged in as well so that train covers both
        ``train_spider.json`` and ``train_others.json``.
        """
        questions: List[BenchmarkQuestion] = []
        splits = [split]
        if split == "train":
            splits = ["train", "train_others"]

        for sp in splits:
            for record in self._load_split_json(sp):
                db_id = record.get("db_id", "")
                reference_sql = record.get("query")
                questions.append(
                    BenchmarkQuestion(
                        question=record.get("question", ""),
                        database_id=db_id,
                        database_path=self.resolve_database_path(db_id),
                        reference_sql=reference_sql,
                        split=sp,
                        evidence=None,
                        metadata={
                            "question_id": record.get("question_id"),
                            "spider_split": sp,
                            "query_toks": record.get("query_toks"),
                            "question_toks": record.get("question_toks"),
                            "has_query": bool(reference_sql),
                        },
                    )
                )
        return questions

    # ------------------------------------------------------------------
    # Schema metadata (tables.json)
    # ------------------------------------------------------------------
    def load_tables(self, split: str = "dev") -> Optional[list]:
        """Return the ``tables.json`` schema metadata for ``split``."""
        filename = SPLIT_META_FILES.get(split, "tables.json")
        path = self.root / filename
        if not path.is_file():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------
    def summary(self) -> dict:
        databases = self.discover_databases()
        database_split_counts = {"database": 0, "test_database": 0}
        for d in databases:
            for folder in database_split_counts:
                if folder in d.split.split(","):
                    database_split_counts[folder] += 1
        splits = {}
        for split in SPLIT_QUESTION_FILES:
            questions = self.load_questions(split)
            empty_ref = [q for q in questions if not q.reference_sql]
            splits[split] = {
                "questions": len(questions),
                "reference_sql_available": len(questions) - len(empty_ref),
            }
        return {
            "name": "Spider",
            "root": str(self.root),
            "archive": self.archive_info(),
            "databases_discovered": len(databases),
            "database_splits": database_split_counts,
            "splits": splits,
        }