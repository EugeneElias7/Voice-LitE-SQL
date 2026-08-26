"""Voice-LitE-SQL -- Level 10: BIRD benchmark loader.

Loads the BIRD Mini-Dev SQLite portion (``minidev_0703``) and the matching
question/reference-SQL records (``mini_dev_sqlite.json`` / gold file).
Discovers:

- SQLite databases under ``dev_databases/<db_id>/<db_id>.sqlite``
- question records with ``question_id``, ``db_id``, ``question``,
  ``evidence``, ``difficulty`` and gold ``SQL``
- gold SQL in ``mini_dev_sqlite_gold.sql`` (``SQL<TAB>db_id`` per line)
- schema meta in ``dev_tables.json``

Native record fields are preserved in ``metadata``; nothing here assumes the
Enterprise database schema.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from backend.benchmarks.models import BenchmarkDatabase, BenchmarkQuestion

# Name of the question file inside the extracted BIRD Mini-Dev package.
QUESTION_FILES = ("mini_dev_sqlite.json",)
GOLD_FILES = ("mini_dev_sqlite_gold.sql",)
META_FILE = "dev_tables.json"


class BirdNotFound(RuntimeError):
    """Raised when the BIRD Mini-Dev root cannot be located."""


class BirdLoader:
    """Discover and load questions/databases from an extracted BIRD root.

    Parameters
    ----------
    root:
        directory that contains ``dev_databases/`` and ``mini_dev_sqlite.json``
        (the extracted ``minidev/MINIDEV`` folder).
    questions_file:
        optional explicit path to the questions JSON (defaults to
        ``mini_dev_sqlite.json`` under root).
    """

    def __init__(
        self,
        root: str,
        questions_file: Optional[str] = None,
    ):
        self.root = Path(root)
        self.questions_file = Path(questions_file) if questions_file else self.root / QUESTION_FILES[0]
        if not self.root.is_dir():
            raise BirdNotFound(
                f"BIRD root not found: {self.root}. "
                "Extract the minidev package so that dev_databases/ and "
                "mini_dev_sqlite.json are under root."
            )
        if not self.questions_file.is_file():
            raise BirdNotFound(
                f"BIRD questions file not found: {self.questions_file}"
            )

    # ------------------------------------------------------------------
    # Database discovery
    # ------------------------------------------------------------------
    def discover_databases(self) -> List[BenchmarkDatabase]:
        """Find all SQLite databases under ``dev_databases``."""
        base = self.root / "dev_databases"
        found: Dict[str, BenchmarkDatabase] = {}
        if base.is_dir():
            for sqlite in sorted(base.glob("*/*.sqlite")):
                db_id = sqlite.parent.name
                found[db_id] = BenchmarkDatabase(
                    database_id=db_id,
                    path=str(sqlite.resolve()),
                    split="dev",
                )
        return sorted(found.values(), key=lambda d: d.database_id)

    def resolve_database_path(self, db_id: str) -> Optional[str]:
        candidate = self.root / "dev_databases" / db_id / f"{db_id}.sqlite"
        if candidate.is_file():
            return str(candidate.resolve())
        return None

    # ------------------------------------------------------------------
    # Question / reference SQL loading
    # ------------------------------------------------------------------
    def _load_questions(self) -> List[dict]:
        with open(self.questions_file, encoding="utf-8") as f:
            return json.load(f)

    def _load_gold_map(self) -> Dict[int, str]:
        """Parse ``mini_dev_sqlite_gold.sql`` into ``{question_id: sql}``.

        Each line is ``<SQL>\t<db_id>``. The gold file is row-ordered
        identically to the questions JSON, so we match by position.
        """
        gold_path = self.root / GOLD_FILES[0]
        if not gold_path.is_file():
            return {}
        with open(gold_path, encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f if line.strip()]
        questions = self._load_questions()
        mapping: Dict[int, str] = {}
        for i, q in enumerate(questions):
            if i < len(lines) and "\t" in lines[i]:
                sql = lines[i].split("\t", 1)[0].strip()
                mapping[q.get("question_id")] = sql
        return mapping

    def load_questions(self, split: str = "dev") -> List[BenchmarkQuestion]:
        """Load normalized questions for ``split`` (only "dev" in Mini-Dev).

        Reference SQL is taken from the record's ``SQL`` field; the gold SQL
        file is used as a fallback when a record has no inline SQL.
        """
        gold_map = self._load_gold_map()
        questions: List[BenchmarkQuestion] = []
        for record in self._load_questions():
            qid = record.get("question_id")
            reference_sql = record.get("SQL")
            if not reference_sql:
                reference_sql = gold_map.get(qid)
            db_id = record.get("db_id", "")
            questions.append(
                BenchmarkQuestion(
                    question=record.get("question", ""),
                    database_id=db_id,
                    database_path=self.resolve_database_path(db_id),
                    reference_sql=reference_sql,
                    split=split,
                    evidence=record.get("evidence"),
                    metadata={
                        "question_id": qid,
                        "difficulty": record.get("difficulty"),
                        "has_SQL": bool(record.get("SQL")),
                    },
                )
            )
        return questions

    # ------------------------------------------------------------------
    # Schema metadata (dev_tables.json)
    # ------------------------------------------------------------------
    def load_tables(self) -> Optional[list]:
        path = self.root / META_FILE
        if not path.is_file():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------
    def summary(self) -> dict:
        databases = self.discover_databases()
        questions = self.load_questions()
        empty_ref = [q for q in questions if not q.reference_sql]
        return {
            "name": "BIRD (Mini-Dev, SQLite)",
            "root": str(self.root),
            "questions_file": str(self.questions_file),
            "databases_discovered": len(databases),
            "questions": len(questions),
            "reference_sql_available": len(questions) - len(empty_ref),
            "splits": {"dev": len(questions)},
        }