#!/usr/bin/env python3
"""Voice-LitE-SQL -- Level 10: dataset integrity/preparation validation.

Produces ``evaluation/results/l10_dataset_validation.json`` describing the
external Spider + BIRD datasets that were downloaded and prepared. The report
contains verification facts only -- never benchmark accuracy.

Usage:
    python scripts/l10_dataset_validate.py [--report path]
"""

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.benchmarks import BirdLoader, SpiderLoader
from backend.database.schema_inspector import inspect_database

RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
SPIDER_ROOT = PROJECT_ROOT / "backend" / "datasets" / "external" / "spider" / "spider_data"
BIRD_ROOT = PROJECT_ROOT / "backend" / "datasets" / "external" / "bird" / "minidev" / "MINIDEV"
SPIDER_ARCHIVE = PROJECT_ROOT / "backend" / "datasets" / "external" / "spider" / "spider_data.zip"
BIRD_ARCHIVE = PROJECT_ROOT / "backend" / "datasets" / "external" / "bird" / "minidev_0703.zip"
INDEX_ROOT = PROJECT_ROOT / "datasets" / "external" / "indexes"


def l2_stats(loader, max_dbs=1_000_000):
    """Inspect every discovered database with L2; return integrity stats."""
    dbs = loader.discover_databases()
    stats = {
        "databases_discovered": len(dbs),
    }
    tables = columns = fks = ok = failed = 0
    failures = []
    for db in dbs:
        if not db.path:
            failed += 1
            failures.append(db.database_id)
            continue
        try:
            schema = inspect_database(db.path)
            tables += len(schema.tables)
            columns += sum(len(t.columns) for t in schema.tables)
            fks += sum(len(t.foreign_keys) for t in schema.tables)
            ok += 1
        except Exception as exc:  # noqa: BLE001 - collect any inspection error
            failed += 1
            failures.append(f"{db.database_id}: {exc}")
    stats.update({
        "l2_ok": ok,
        "l2_failed": failed,
        "l2_failures": failures[:10],
        "tables_inspected": tables,
        "columns_inspected": columns,
        "foreign_keys_inspected": fks,
    })
    return stats


def question_stats(questions):
    """Per-split question counts + reference SQL + duplicate ID detection."""
    by_db = Counter(q.database_id for q in questions)
    qids = [q.metadata.get("question_id") for q in questions if q.metadata.get("question_id") is not None]
    dup_qids = [qid for qid, n in Counter(qids).items() if n > 1]
    return {
        "questions": len(questions),
        "databases_referenced": len(by_db),
        "reference_sql_available": sum(1 for q in questions if q.reference_sql),
        "reference_sql_missing": sum(1 for q in questions if not q.reference_sql),
        "evidence_available": sum(1 for q in questions if q.evidence),
        "database_path_resolved": sum(1 for q in questions if q.database_path),
        "database_path_missing": sum(1 for q in questions if not q.database_path),
        "duplicate_question_ids": len(dup_qids),
        "duplicate_question_id_examples": dup_qids[:5],
    }


def main(argv=None):
    report_path = Path(argv[0]) if argv else RESULTS_DIR / "l10_dataset_validation.json"
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "scope": "dataset acquisition & preparation (no benchmark evaluation run)",
    }

    # ------------------------------------------------------------------
    # Spider
    # ------------------------------------------------------------------
    if SPIDER_ROOT.is_dir():
        spider = SpiderLoader(str(SPIDER_ROOT), archive_path=str(SPIDER_ARCHIVE))
        spider_l2 = l2_stats(spider)
        splits = {}
        for split in ("train", "train_others", "dev", "test"):
            questions = spider.load_questions(split)
            splits[split] = question_stats(questions)
        spider_tables = spider.load_tables("dev")
        spider_test_tables = spider.load_tables("test")
        report["spider"] = {
            "source": "Official Spider dataset (Yale LILY), CC BY-SA 4.0",
            "archive": spider.archive_info(),
            "root": str(SPIDER_ROOT),
            "databases": spider_l2,
            "questions_by_split": splits,
            "tables_json_dev_entries": len(spider_tables or []),
            "tables_json_test_entries": len(spider_test_tables or []),
            "loader": "backend.benchmarks.spider_loader.SpiderLoader",
        }
    else:
        report["spider"] = {"error": "Spider root not present"}

    # ------------------------------------------------------------------
    # BIRD Mini-Dev
    # ------------------------------------------------------------------
    if BIRD_ROOT.is_dir():
        bird = BirdLoader(str(BIRD_ROOT))
        bird_l2 = l2_stats(bird)
        questions = bird.load_questions()
        report["bird"] = {
            "source": "BIRD Mini-Dev 0703 (official), for non-commercial research use",
            "package": {
                "path": str(BIRD_ARCHIVE),
                "size_bytes": BIRD_ARCHIVE.stat().st_size if BIRD_ARCHIVE.is_file() else None,
            },
            "root": str(BIRD_ROOT),
            "databases": bird_l2,
            "questions": question_stats(questions),
            "tables_json_entries": len(bird.load_tables() or []),
            "loader": "backend.benchmarks.bird_loader.BirdLoader",
        }
    else:
        report["bird"] = {"error": "BIRD root not present"}

    # ------------------------------------------------------------------
    # Retrieval index preparation status
    # ------------------------------------------------------------------
    built = list(INDEX_ROOT.rglob("_built_sample.json"))
    if built:
        with open(built[0], encoding="utf-8") as f:
            sample = json.load(f)
        report["retrieval_index_preparation"] = {
            "index_root": str(INDEX_ROOT),
            "mechanism": "backend.benchmarks.indexing.build_external_index",
            "derived_from": "L2 Schema Inspector (no Enterprise schema)",
            "sample_databases_indexed": len(sample),
            "sample_dbs": [s["database_id"] for s in sample],
            "total_documents_indexed": sum(s["documents"] for s in sample),
            "note": "Full benchmark index build deferred to evaluation time; "
                    "verification done on representative sample DBs.",
        }
    else:
        report["retrieval_index_preparation"] = {
            "index_root": str(INDEX_ROOT),
            "status": "no sample index found",
        }

    REPORT_HEADER = {
        "note": "This report contains dataset integrity facts only. "
                "No benchmark accuracy is reported.",
        "frozen_results_untouched": {
            "L4": "40%", "L7": "36%", "L8": "48%",
            "L8.1": "54%", "L9_text": "58%", "L9_audio": "50% (4/8)",
        },
    }
    report = {**REPORT_HEADER, **report}

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report saved: {report_path}")

    # Console summary
    for key in ("spider", "bird"):
        entry = report.get(key, {})
        if "error" in entry:
            print(f"{key}: ERROR {entry['error']}")
            continue
        dbs = entry.get("databases", {})
        print(f"{key}: dbs={dbs.get('databases_discovered')} "
              f"L2_ok={dbs.get('l2_ok')} tables={dbs.get('tables_inspected')} "
              f"cols={dbs.get('columns_inspected')} fks={dbs.get('foreign_keys_inspected')}")
        if key == "spider":
            for split, st in entry["questions_by_split"].items():
                print(f"    {split:12s} q={st['questions']:5d} ref_sql={st['reference_sql_available']:5d}")
        else:
            st = entry["questions"]
            print(f"    dev: q={st['questions']} ref_sql={st['reference_sql_available']} "
                  f"evidence={st['evidence_available']} dup_ids={st['duplicate_question_ids']}")
    ret = report["retrieval_index_preparation"]
    print(f"retrieval_index: {ret.get('sample_databases_indexed', 0)} sample DBs indexed @ {ret.get('index_root')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))