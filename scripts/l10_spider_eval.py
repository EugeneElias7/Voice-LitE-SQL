#!/usr/bin/env python3
"""Voice-LitE-SQL -- Level 10: Spider dev-set evaluation (frozen L9 pipeline).

Runs the official Spider dev split (1,034 questions / 20 databases) through
the frozen L9 ``VoiceLitESQLPipeline`` on a per-``db_id`` basis. Each database
gets one cached pipeline instance whose SchemaRetriever is built from the L2
schema inspector (index persisted per database, so chunks reuse indexes).

Run in chunks to stay within shell timeouts, then merge:

    python scripts/l10_spider_eval.py --offset 0 --limit 100
    python scripts/l10_spider_eval.py --offset 100 --limit 100
    ...
    python scripts/l10_spider_eval.py --merge

The merged report (``evaluation/results/l10_spider_dev_report.json``) contains
evaluation metrics only -- the frozen baselines are never recomputed.
"""

import argparse
import hashlib
import json
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.benchmarks import SpiderLoader  # noqa: E402
from backend.benchmarks.indexing import default_index_dir  # noqa: E402
from backend.evaluation.metrics import compute_metrics  # noqa: E402
from backend.pipeline.voice_lite_sql import (  # noqa: E402
    PipelineConfig,
    VoiceLitESQLPipeline,
)
from backend.retrieval import (  # noqa: E402
    SchemaRetriever,
    SentenceTransformerEmbedder,
)
from backend.retrieval.embeddings import EMBEDDING_DIMENSIONS  # noqa: E402
from backend.retrieval.schema_documents import documents_by_id  # noqa: E402
from backend.llm.ollama_client import DEFAULT_MODEL  # noqa: E402

RESULTS_DIR = PROJECT_ROOT / "evaluation" / "results"
SPIDER_ROOT = PROJECT_ROOT / "backend" / "datasets" / "external" / "spider" / "spider_data"
INDEX_ROOT = PROJECT_ROOT / "datasets" / "external" / "indexes"
CHUNK_PREFIX = "l10_spider_dev_chunk"

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
TOP_K = 5


def db_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_pipeline_for_db(db_path, db_id, shared_embedder):
    """Create a frozen L9 pipeline for one external database.

    A dedicated SchemaRetriever (same class the L9 pipeline instantiates)
    is built once per database and injected so the embedding model is loaded
    once per process instead of once per database. Index persists to disk,
    so chunked runs reuse it.
    """
    index_dir = default_index_dir(str(INDEX_ROOT), db_id, db_path)
    persist_dir = index_dir
    persist_dir.mkdir(parents=True, exist_ok=True)

    config = PipelineConfig(
        db_path=db_path,
        index_dir=str(persist_dir),
        embedding_model=EMBEDDING_MODEL,
        top_k=TOP_K,
        max_correction_attempts=3,
        correction_timeout=120,
        fake_embedder=False,
        enable_nlp=True,
        enable_correction=True,
        enable_validation=True,
    )

    retriever = SchemaRetriever(
        db_path=db_path,
        persist_dir=str(persist_dir),
        embedding_model=EMBEDDING_MODEL,
        embedding_dimensions=EMBEDDING_DIMENSIONS.get(EMBEDDING_MODEL, 384),
        top_k=TOP_K,
        embedder=shared_embedder,
    )
    # Data quirk in some Spider DBs (e.g. dog_kennels) lists the same FK
    # twice, producing a byte-identical duplicate relationship document.
    # ChromaDB upsert rejects duplicate IDs; first-seen dedup from the frozen
    # documents_by_id is semantically invisible but makes the index buildable.
    seen = set()
    retriever._documents = [
        d for d in retriever._documents
        if not (d.doc_id in seen or seen.add(d.doc_id))
    ]
    retriever._document_by_id = documents_by_id(retriever._documents)
    retriever._index_built = False
    retriever.build_index()

    pipeline = VoiceLitESQLPipeline(config)
    pipeline._retriever = retriever
    return pipeline


def to_evaluation(result, question, db_id):
    """Flatten one frozen L9 PipelineResult into a compact evaluation dict."""
    generation = result.generation
    execution = result.execution
    correction = result.correction
    nlp = result.nlp

    return {
        "question_id": question.metadata.get("question_id"),
        "index": question.metadata.get("index"),
        "db_id": db_id,
        "question": question.question,
        "reference_sql": question.reference_sql,
        "generation_success": bool(generation and generation.generated_sql),
        "generated_sql": generation.generated_sql if generation else "",
        "execution_success": bool(execution and execution.success),
        "execution_error": execution.error if execution else None,
        "execution_error_type": execution.error_type if execution else None,
        "correctness": bool(result.final_correct),
        "total_latency_ms": round(result.total_latency_ms, 2),
        "generation_latency_ms": round(
            (result.stage_latencies.get("generation", 0.0)), 2
        ),
        "correction_total_attempts": correction.total_attempts if correction else 0,
        "correction_rescued": bool(correction and correction.rescued),
        "correction_harmed": bool(correction and correction.harmed),
        "final_sql": result.final_sql,
        "intent": (nlp.intent or {}).get("primary_intent", "") if nlp else "",
    }


class PseudoEval:
    """Adapter so frozen ``compute_metrics`` works on evaluation dicts."""

    def __init__(self, e):
        self._e = e

    @property
    def generation_success(self):
        return self._e["generation_success"]

    @property
    def execution_success(self):
        return self._e["execution_success"]

    @property
    def correctness(self):
        return self._e["correctness"]

    @property
    def execution_time_ms(self):
        return self._e["total_latency_ms"]

    @property
    def category(self):
        return self._e.get("db_id", "")


class PseudoEvalList:
    def __init__(self, evaluations):
        self._items = evaluations

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        for e in self._items:
            yield PseudoEval(e)


PROGRESS_FILE = RESULTS_DIR / "l10_spider_dev_progress.jsonl"


def load_questions():
    loader = SpiderLoader(str(SPIDER_ROOT))
    questions = loader.load_questions("dev")
    for idx, q in enumerate(questions):
        q.metadata["index"] = idx
    return questions


def load_progress():
    """Load previously completed evaluations keyed by question index."""
    done = {}
    if PROGRESS_FILE.is_file():
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                done[ev.get("index")] = ev
    return done


def append_progress(ev):
    with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(ev) + "\n")


def missing_db_evaluation(q):
    return {
        "question_id": q.metadata.get("question_id"),
        "index": q.metadata.get("index"),
        "db_id": q.database_id,
        "question": q.question,
        "reference_sql": q.reference_sql,
        "generation_success": False,
        "generated_sql": "",
        "execution_success": False,
        "execution_error": "database_path_missing",
        "execution_error_type": "database_path_missing",
        "correctness": False,
        "total_latency_ms": 0.0,
        "generation_latency_ms": 0.0,
        "correction_total_attempts": 0,
        "correction_rescued": False,
        "correction_harmed": False,
        "final_sql": "",
        "intent": "",
    }


def timed_out_evaluation(q, seconds):
    return {
        "question_id": q.metadata.get("question_id"),
        "index": q.metadata.get("index"),
        "db_id": q.database_id,
        "question": q.question,
        "reference_sql": q.reference_sql,
        "generation_success": False,
        "generated_sql": "",
        "execution_success": False,
        "execution_error": f"question_timeout_{seconds}s",
        "execution_error_type": "question_timeout",
        "correctness": False,
        "total_latency_ms": seconds * 1000.0,
        "generation_latency_ms": 0.0,
        "correction_total_attempts": 0,
        "correction_rescued": False,
        "correction_harmed": False,
        "final_sql": "",
        "intent": "",
        "timed_out": True,
    }


def run_question_with_timeout(pipeline, q, db_id, timeout_seconds):
    """Run one question; return (ev, finished) or (timeout_ev, False)."""
    result_box = {}

    def work():
        result = pipeline.run_text_query(
            q.question,
            question_id=q.metadata.get("question_id") or f"dev_{q.metadata['index']}",
            category=None,
            reference_sql=q.reference_sql,
        )
        result_box["ev"] = to_evaluation(result, q, db_id)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        return timed_out_evaluation(q, timeout_seconds), False
    return result_box["ev"], True


def run_chunk(offset, limit, report=None, question_timeout=0):
    questions = load_questions()
    chunk = questions[offset:]
    if limit is not None:
        chunk = chunk[:limit]

    done = load_progress()
    pending = [q for q in chunk if q.metadata["index"] not in done]
    print(f"Chunk: offset={offset} limit={limit} questions={len(chunk)} "
          f"(done={len(chunk) - len(pending)}, pending={len(pending)})")

    if not pending:
        print("Nothing to do - all questions in this range already completed.")
        return

    embedder = SentenceTransformerEmbedder(model_name=EMBEDDING_MODEL)
    pipelines = {}

    db_shas = {}
    started = time.perf_counter()

    for q in pending:
        db_id = q.database_id
        if not q.database_path:
            ev = missing_db_evaluation(q)
            append_progress(ev)
            print(f"[{q.metadata['index']}] {db_id}: MISSING DB PATH (recorded)")
            continue

        if db_id not in pipelines:
            stride = time.perf_counter()
            pipelines[db_id] = build_pipeline_for_db(
                q.database_path, db_id, embedder
            )
            db_shas[db_id] = db_sha256(q.database_path)
            print(f"  built pipeline for {db_id} ({time.perf_counter() - stride:.1f}s)")

        pipeline = pipelines[db_id]
        if question_timeout:
            ev, finished = run_question_with_timeout(
                pipeline, q, db_id, question_timeout
            )
            if not finished:
                print(f"[{q.metadata['index']}] {db_id} TIMEOUT after "
                      f"{question_timeout}s (recorded, skipped)")
                pipelines.pop(db_id, None)
        else:
            result = pipeline.run_text_query(
                q.question,
                question_id=q.metadata.get("question_id") or f"dev_{q.metadata['index']}",
                category=None,
                reference_sql=q.reference_sql,
            )
            ev = to_evaluation(result, q, db_id)
        append_progress(ev)

        mark = "OK " if ev["correctness"] else "XX "
        print(f"[{q.metadata['index']}] {db_id} {mark}corr={ev['correctness']} "
              f"exec={ev['execution_success']} attempts={ev['correction_total_attempts']} "
              f"{ev['total_latency_ms']:.0f}ms")

    elapsed = time.perf_counter() - started
    evaluations = list(load_progress().values())

    print(f"Chunk complete: {len(evaluations)}/{len(questions)} total done "
          f"({elapsed / 60:.1f} min this session)")

    # Integrity check: read-only pipeline must leave every db untouched.
    integrity = {}
    for db_id, sha in db_shas.items():
        q_path = next(q.database_path for q in chunk if q.database_id == db_id)
        integrity[db_id] = db_sha256(q_path) == sha

    metrics = compute_metrics(PseudoEvalList(evaluations))
    report_path = Path(report) if report else (
        RESULTS_DIR / f"{CHUNK_PREFIX}_{offset}_{offset + len(chunk)}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "scope": f"Spider dev range [{offset}, {offset + len(chunk)}) (incremental)",
        "offset": offset,
        "limit": limit if limit is not None else len(chunk),
        "questions_done_total": len(evaluations),
        "databases": len(pipelines),
        "elapsed_seconds": round(elapsed, 1),
        "integrity": integrity,
        "progress_file": str(PROGRESS_FILE),
    }, indent=2), encoding="utf-8")
    print(f"Chunk saved: {report_path} (integrity={integrity})")
    return report_path


def merge_reports():
    if not PROGRESS_FILE.is_file():
        print("No progress file found - run evaluation first", file=sys.stderr)
        return 1

    evaluations = sorted(
        load_progress().values(), key=lambda e: e.get("index") or 0
    )
    print(f"Merged {len(evaluations)} evaluations from {PROGRESS_FILE}")

    metrics = compute_metrics(PseudoEvalList(evaluations))

    by_db = {}
    for ev in evaluations:
        by_db.setdefault(ev["db_id"], []).append(ev)
    per_db = {
        db: compute_metrics(PseudoEvalList(evals))
        for db, evals in sorted(by_db.items())
    }

    by_intent = {}
    for ev in evaluations:
        by_intent.setdefault(ev["intent"] or "unknown", []).append(ev)
    per_intent = {
        intent: compute_metrics(PseudoEvalList(evals))
        for intent, evals in sorted(by_intent.items())
    }

    rescued = [e for e in evaluations if e.get("correction_rescued")]
    harmed = [e for e in evaluations if e.get("correction_harmed")]
    gen_failed = [e for e in evaluations if not e.get("generation_success")]
    exec_failed = [e for e in evaluations if not e.get("execution_success")]
    error_types = Counter(
        e.get("execution_error_type") or "none" for e in exec_failed
    )
    attempts_dist = Counter(
        e.get("correction_total_attempts", 0) for e in evaluations
    )

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "task": "Spider dev execution accuracy (frozen L9 pipeline per db_id)",
        "split": "dev",
        "questions_total": 1034,
        "questions_evaluated": len(evaluations),
        "databases_used": len(by_db),
        "model": DEFAULT_MODEL,
        "embedding_model": EMBEDDING_MODEL,
        "top_k": TOP_K,
        "metrics": metrics,
        "per_database": per_db,
        "per_intent": per_intent,
        "correction": {
            "rescued": len(rescued),
            "harmed": len(harmed),
            "attempts_distribution": dict(sorted(attempts_dist.items())),
        },
        "generation_failures": len(gen_failed),
        "execution_failures": len(exec_failed),
        "execution_error_type_counts": dict(sorted(error_types.items())),
        "frozen_baselines": {
            "L4": "40%", "L7": "36%", "L8": "48%",
            "L8.1": "54%", "L9_text": "58%", "L9_audio": "50% (4/8)",
            "note": "Spider/Enterprise corpora differ; monitoring metric only.",
        },
        "chunk_files": [str(PROGRESS_FILE)],
        "evaluations": evaluations,
    }

    report_path = RESULTS_DIR / "l10_spider_dev_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Merged report saved: {report_path}")
    print(json.dumps(metrics, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="L10 Spider dev evaluation")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report", default=None)
    parser.add_argument(
        "--question-timeout", type=int, default=0,
        help="per-question wall-clock cap in seconds (0 = no cap); "
             "a timed-out question is recorded and skipped on resume",
    )
    parser.add_argument("--merge", action="store_true",
                        help="merge all chunk reports into the final report")
    args = parser.parse_args(argv)

    if args.merge:
        return merge_reports()

    run_chunk(args.offset, args.limit, report=args.report,
              question_timeout=args.question_timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())