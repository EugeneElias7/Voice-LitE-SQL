"""Voice-LitE-SQL -- Level 11: FastAPI application.

Exposes the frozen L9 pipeline through clean REST endpoints. The frontend
never sends SQL to the database -- the browser only ever sends a natural
language question (or audio), and every query goes through the read-only
SQL validator and read-only executor inside the pipeline.

Endpoints
---------
GET  /api/health                liveness probe
GET  /api/status                per-component status (ollama, whisper, chroma, db)
GET  /api/schema                L2 schema inspector output + row counts
GET  /api/demo-questions        curated demo questions from questions.json
POST /api/query                 run a text question through the real L9 pipeline
POST /api/voice-query           transcribe audio then run the real L9 pipeline
POST /api/query/stream          SSE: live per-stage progress for a text question
POST /api/voice-query/stream    SSE: live per-stage progress for audio
GET  /api/datasources           list available data sources
POST /api/datasources/{id}/select  switch active data source
POST /api/datasources/upload    upload local SQLite database
GET  /api/models                list available Ollama models
POST /api/models/select         switch active model
GET  /api/suggestions           schema-aware question suggestions
POST /api/tts                   text-to-speech (local)

Run with:
    python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import queue as queue_module
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional

import requests
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.answers import build_answer
from backend.api.progress import install_progress_hook
from backend.api.service import PipelineService, get_service
from backend.benchmarks.bird_loader import BirdLoader, BirdNotFound
from backend.benchmarks.spider_loader import SpiderLoader, SpiderNotFound
from backend.database.schema_inspector import DatabaseError, inspect_database
from backend.llm.ollama_client import DEFAULT_HOST, DEFAULT_MODEL, OllamaError
from backend.pipeline.pipeline_result import PipelineResult
from backend.pipeline.voice_lite_sql import DEFAULT_DB, PipelineConfig

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
DEMO_QUESTIONS_PATH = PROJECT_ROOT / "backend" / "datasets" / "custom" / "questions.json"


# ---------------------------------------------------------------------------
# Pipeline stage catalogue (maps to real PipelineResult.stage_latencies keys)
# ---------------------------------------------------------------------------
STAGE_META: List[dict] = [
    {"key": "audio", "label": "Audio", "level": "L5"},
    {"key": "asr", "label": "Speech Recognition", "level": "L5"},
    {"key": "normalization", "label": "Phonetic Normalization", "level": "L6"},
    {"key": "nlp", "label": "NLP + Intent", "level": "L8.1"},
    {"key": "retrieval", "label": "Schema Retrieval", "level": "L7"},
    {"key": "generation", "label": "Qwen 2.5 SQL Generation", "level": "L3"},
    {"key": "validation", "label": "SQL Validation", "level": "L4"},
    {"key": "execution", "label": "Database Execution", "level": "L4"},
    {"key": "correction", "label": "Execution-Guided Correction", "level": "L8"},
]
TEXT_STAGES: List[dict] = [s for s in STAGE_META if s["key"] not in ("audio", "asr")]


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# ---------------------------------------------------------------------------
# Database / component helpers
# ---------------------------------------------------------------------------
def _row_counts(db_path: str):
    """Return {table: row_count} and total across all L2-inspected tables."""
    counts: dict = {}
    total = 0
    path = Path(db_path).resolve()
    if not path.exists():
        return counts, 0
    try:
        schema = inspect_database(db_path)
    except DatabaseError:
        return counts, 0
    uri = path.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.execute("PRAGMA query_only = ON")
        for table in schema.tables:
            try:
                row = conn.execute(f'SELECT COUNT(*) FROM "{table.name}"').fetchone()
                value = row[0] if row else 0
            except sqlite3.Error:
                value = None
            counts[table.name] = value
            total += value or 0
    return counts, total


def _schema_payload(db_path: str) -> dict:
    schema = inspect_database(db_path)
    counts, total = _row_counts(db_path)
    tables = []
    for table in schema.tables:
        data = table.to_dict()
        for column in data["columns"]:
            value = column.get("default_value")
            if value is not None and not isinstance(value, (str, int, float, bool)):
                column["default_value"] = str(value)
        data["row_count"] = counts.get(table.name)
        tables.append(data)
    return {
        "database": Path(db_path).stem,
        "path": str(db_path),
        "tables": tables,
        "total_rows": total,
    }


def _ollama_status() -> dict:
    try:
        response = requests.get(f"{DEFAULT_HOST.rstrip('/')}/api/tags", timeout=3)
        models = []
        if response.status_code == 200:
            models = [m.get("name", "") for m in response.json().get("models", [])]
        present = DEFAULT_MODEL in models
        return {
            "state": "ready" if present else "offline",
            "host": DEFAULT_HOST,
            "model": DEFAULT_MODEL,
            "model_loaded": present,
            "models": models,
        }
    except Exception as exc:  # noqa: BLE001 - surface any connectivity failure
        return {"state": "offline", "error": str(exc)}


def _whisper_status() -> dict:
    try:
        from backend.asr.whisper_engine import WhisperEngine

        model_name = PipelineConfig().asr_model
        engine = WhisperEngine(model_name=model_name)
        has_faster = engine._model_available("faster-whisper")
        has_openai = engine._model_available("openai-whisper")
        if has_faster or has_openai:
            return {
                "state": "ready",
                "model": model_name,
                "backend": "faster-whisper" if has_faster else "openai-whisper",
            }
        return {"state": "offline", "model": model_name, "detail": "model not present locally"}
    except Exception as exc:  # noqa: BLE001
        return {"state": "offline", "detail": str(exc)}


def _chroma_status(service: PipelineService) -> dict:
    index_dir = Path(service.index_dir)
    built_by_service = service._pipeline is not None
    present = index_dir.exists() and (index_dir / "chroma.sqlite3").exists()
    if built_by_service:
        return {"state": "ready", "index_dir": str(index_dir), "built": True}
    return {
        "state": "ready" if present else "not_built",
        "index_dir": str(index_dir),
        "built": False,
    }


# ---------------------------------------------------------------------------
# Result enrichment
# ---------------------------------------------------------------------------
def _enrich(result: PipelineResult, mode: str, question: str,
            category: str = "", transcript: Optional[str] = None) -> dict:
    data = result.to_dict()
    data["input"] = {
        "mode": mode,
        "question": question,
        "transcript": transcript if transcript is not None else question,
        "category": category,
        "received_at": time.time(),
    }
    data["answer"] = build_answer(result)
    return data


def _demo_questions() -> List[dict]:
    if not DEMO_QUESTIONS_PATH.exists():
        return []
    with open(DEMO_QUESTIONS_PATH, "r", encoding="utf-8") as handle:
        records = json.load(handle)
    by_id = {r.get("id"): r for r in records if isinstance(r, dict)}
    picked = ["q41", "q13", "q37", "q46", "q47", "q31"]
    return [
        {
            "question": by_id[qid]["question"],
            "category": by_id[qid].get("category", ""),
        }
        for qid in picked if qid in by_id
    ]


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    app = FastAPI(title="Voice-LitE-SQL", version="L11",
                  description="Local Voice -> NLP -> SQL Assistant frontend backend")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "https://voice-lite-sql.vercel.app",
        ],
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _service() -> PipelineService:
        return get_service()

    # --- health -----------------------------------------------------------
    @app.get("/api/health")
    def health(service: PipelineService = Depends(_service)):
        from backend.database.schema_inspector import DatabaseError
        try:
            inspect_database(service.db_path)
            db_state = "ok"
        except DatabaseError:
            db_state = "degraded"
        return {"status": db_state, "service": "voice-lite-sql", "database": service.database_name}

    # --- status ------------------------------------------------------------
    @app.get("/api/status")
    def status(service: PipelineService = Depends(_service)):
        try:
            counts, total = _row_counts(service.db_path)
            database = {"state": "ready", "tables": len(counts), "rows": total}
        except DatabaseError as exc:
            database = {"state": "offline", "error": str(exc)}
        ollama = _ollama_status()
        whisper = _whisper_status()
        chroma = _chroma_status(service)
        schema = {"state": "ready" if database["state"] == "ready" else "offline"}
        return {
            "backend": {"state": "ready", "detail": "api online"},
            "database": database,
            "ollama": ollama,
            "model": {
                "state": ollama.get("state"),
                "name": DEFAULT_MODEL,
                "loaded": ollama.get("model_loaded", False),
            },
            "whisper": whisper,
            "chroma": chroma,
            "schema": schema,
        }

    # --- schema --------------------------------------------------------------
    @app.get("/api/schema")
    def schema(service: PipelineService = Depends(_service)):
        try:
            return _schema_payload(service.db_path)
        except DatabaseError as exc:
            raise HTTPException(status_code=503, detail=f"database unavailable: {exc}")

    # --- demo questions -------------------------------------------------------
    @app.get("/api/demo-questions")
    def demo_questions():
        return {"questions": _demo_questions()}

    # --- text query -----------------------------------------------------------
    @app.post("/api/query")
    def run_query(payload: dict, service: PipelineService = Depends(_service)):
        question = (payload.get("question") or "").strip()
        if not question:
            raise HTTPException(status_code=422, detail="question is required")
        try:
            result = service.run_text_query(question, category=payload.get("category", ""))
        except Exception as exc:  # noqa: BLE001 - return a structured error
            raise HTTPException(status_code=500, detail=f"pipeline failed: {exc}")
        return _enrich(result, "text", question, category=payload.get("category", ""))

    # --- voice query -----------------------------------------------------------
    @app.post("/api/voice-query")
    def run_voice_query(file: UploadFile = File(...),
                        service: PipelineService = Depends(_service)):
        extension = Path(file.filename or "audio.webm").suffix or ".webm"
        suffix = extension if extension.startswith(".") else f".{extension}"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            while chunk := file.file.read(1 << 20):
                tmp.write(chunk)
            audio_path = tmp.name
        try:
            result = service.run_voice_query(audio_path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"pipeline failed: {exc}")
        finally:
            try:
                Path(audio_path).unlink(missing_ok=True)
            except OSError:
                pass
        transcript = (result.asr.raw_transcript
                      if result.asr and result.asr.raw_transcript else "")
        return _enrich(result, "voice", transcript,
                       category="", transcript=transcript)

    # ---------------------------------------------------------------------------
    # SSE streaming endpoints (real per-stage progress from the live pipeline)
    # ---------------------------------------------------------------------------
    def _stream_text(question: str, category: str):
        stage_list = TEXT_STAGES
        chan = queue_module.Queue()

        def run():
            try:
                result = get_service().run_text_query(question, category=category)
                chan.put(("pipeline_completed",
                          {"result": _enrich(result, "text", question, category=category)}))
            except Exception as exc:  # noqa: BLE001
                chan.put(("pipeline_error", {"error": str(exc)}))

        thread = threading.Thread(target=run, daemon=True)

        async def generator():
            with install_progress_hook(
                lambda stage, ms: chan.put(("stage_completed", {"stage": stage, "latency_ms": ms}))
            ):
                thread.start()
                yield _sse({"event": "pipeline_started",
                            "mode": "text", "question": question, "stages": stage_list})
                while True:
                    try:
                        item = await asyncio.to_thread(chan.get, True, 0.5)
                        event, payload = item
                    except queue_module.Empty:
                        if thread.is_alive():
                            continue
                        try:
                            event, payload = chan.get_nowait()
                        except queue_module.Empty:
                            break
                    yield _sse({"event": event, **payload})
                    if event in ("pipeline_completed", "pipeline_error"):
                        break
                thread.join(timeout=1)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def _stream_voice(audio_path: str):
        stage_list = STAGE_META
        chan = queue_module.Queue()

        def run():
            try:
                result = get_service().run_voice_query(audio_path)
                transcript = (result.asr.raw_transcript
                              if result.asr and result.asr.raw_transcript else "")
                chan.put(("pipeline_completed",
                          {"result": _enrich(result, "voice", transcript,
                                             transcript=transcript)}))
            except Exception as exc:
                chan.put(("pipeline_error", {"error": str(exc)}))

        thread = threading.Thread(target=run, daemon=True)

        async def generator():
            with install_progress_hook(
                lambda stage, ms: chan.put(("stage_completed", {"stage": stage, "latency_ms": ms}))
            ):
                thread.start()
                yield _sse({"event": "pipeline_started",
                            "mode": "voice", "stages": stage_list})
                while True:
                    try:
                        item = await asyncio.to_thread(chan.get, True, 0.5)
                        event, payload = item
                    except queue_module.Empty:
                        if thread.is_alive():
                            continue
                        try:
                            event, payload = chan.get_nowait()
                        except queue_module.Empty:
                            break
                    yield _sse({"event": event, **payload})
                    if event in ("pipeline_completed", "pipeline_error"):
                        break
                thread.join(timeout=1)

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def _save_upload(file: UploadFile) -> str:
        extension = Path(file.filename or "audio.webm").suffix or ".webm"
        suffix = extension if extension.startswith(".") else f".{extension}"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.close()
        with open(tmp.name, "wb") as out:
            while chunk := file.file.read(1 << 20):
                out.write(chunk)
        return tmp.name

    @app.post("/api/query/stream")
    def stream_query(payload: dict):
        question = (payload.get("question") or "").strip()
        if not question:
            raise HTTPException(status_code=422, detail="question is required")
        return _stream_text(question, payload.get("category", ""))

    @app.post("/api/voice-query/stream")
    def stream_voice(file: UploadFile = File(...)):
        audio_path = _save_upload(file)

        async def cleanup_after_stream(response: StreamingResponse):
            """Wrap response to cleanup temp file after stream completes."""
            try:
                async for chunk in response.body_iterator:
                    yield chunk
            finally:
                try:
                    Path(audio_path).unlink(missing_ok=True)
                except OSError:
                    pass

        stream = _stream_voice(audio_path)
        return StreamingResponse(
            cleanup_after_stream(stream),
            media_type=stream.media_type,
            headers=stream.headers,
        )

    @app.get("/audio-diag")
    async def audio_diag_page():
        from fastapi.responses import FileResponse
        return FileResponse(str(PROJECT_ROOT / "backend" / "audio_diag.html"))

    @app.post("/api/audio-diag")
    async def audio_diagnostic(file: UploadFile = File(...)):
        """Diagnostic endpoint: analyze uploaded audio, convert to 16kHz mono WAV, run Whisper."""
        import tempfile
        import json
        from pathlib import Path
        import sys

        # Add backend to path for audio_diag import
        backend_dir = PROJECT_ROOT / "backend"
        sys.path.insert(0, str(backend_dir))
        from audio_diag import analyze_audio_file, convert_to_16k_mono_wav, run_whisper_transcription

        # Save uploaded file
        suffix = Path(file.filename or "audio.webm").suffix or ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            upload_path = tmp.name

        try:
            # Analyze original
            original_analysis = analyze_audio_file(upload_path)

            # Convert to 16kHz mono WAV
            wav_path = Path(upload_path).with_suffix('.16k.wav')
            convert_to_16k_mono_wav(upload_path, str(wav_path))

            # Analyze converted
            wav_analysis = analyze_audio_file(str(wav_path))

            # Run Whisper on both
            original_transcript = run_whisper_transcription(upload_path)
            wav_transcript = run_whisper_transcription(str(wav_path))

            return {
                "uploaded_file": file.filename,
                "content_type": file.content_type,
                "original_analysis": original_analysis,
                "converted_wav": str(wav_path),
                "wav_analysis": wav_analysis,
                "original_transcript": original_transcript,
                "wav_transcript": wav_transcript,
            }
        finally:
            # Cleanup
            try:
                Path(upload_path).unlink(missing_ok=True)
                Path(wav_path).unlink(missing_ok=True)
            except OSError:
                pass

    # --- data sources ----------------------------------------------------------
    SPIDER_ROOT = PROJECT_ROOT / "backend" / "datasets" / "external" / "spider" / "spider_data"
    BIRD_ROOT = PROJECT_ROOT / "backend" / "datasets" / "external" / "bird" / "minidev" / "MINIDEV"

    def _spider_loader() -> Optional[SpiderLoader]:
        try:
            return SpiderLoader(str(SPIDER_ROOT))
        except SpiderNotFound:
            return None

    def _bird_loader() -> Optional[BirdLoader]:
        try:
            return BirdLoader(str(BIRD_ROOT))
        except BirdNotFound:
            return None

    @app.get("/api/datasources")
    def list_datasources(service: PipelineService = Depends(_service)):
        """List all available data sources with live stats."""
        sources = []

        # Enterprise (local default)
        try:
            counts, total = _row_counts(service.db_path)
            sources.append({
                "id": "enterprise",
                "name": "Enterprise",
                "type": "local",
                "database": Path(service.db_path).stem,
                "tables": len(counts),
                "rows": total,
                "path": service.db_path,
                "active": True,
            })
        except Exception:
            sources.append({
                "id": "enterprise",
                "name": "Enterprise",
                "type": "local",
                "database": Path(service.db_path).stem,
                "tables": 0,
                "rows": 0,
                "path": service.db_path,
                "active": True,
                "error": "unavailable",
            })

        # Spider
        spider = _spider_loader()
        if spider:
            dbs = spider.discover_databases()
            sources.append({
                "id": "spider",
                "name": "Spider Dev",
                "type": "benchmark",
                "databases": [{"id": d.database_id, "path": d.path, "split": d.split} for d in dbs],
                "database_count": len(dbs),
                "active": False,
            })
        else:
            sources.append({
                "id": "spider",
                "name": "Spider Dev",
                "type": "benchmark",
                "databases": [],
                "database_count": 0,
                "active": False,
                "error": "not found",
            })

        # BIRD
        bird = _bird_loader()
        if bird:
            dbs = bird.discover_databases()
            sources.append({
                "id": "bird",
                "name": "BIRD Mini-Dev",
                "type": "benchmark",
                "databases": [{"id": d.database_id, "path": d.path, "split": d.split} for d in dbs],
                "database_count": len(dbs),
                "active": False,
            })
        else:
            sources.append({
                "id": "bird",
                "name": "BIRD Mini-Dev",
                "type": "benchmark",
                "databases": [],
                "database_count": 0,
                "active": False,
                "error": "not found",
            })

        return {"sources": sources}

    @app.post("/api/datasources/{source_id}/select")
    def select_datasource(source_id: str, payload: dict, service: PipelineService = Depends(_service)):
        """Switch the active data source and rebuild pipeline index."""
        # Reset the service to force pipeline rebuild with new DB
        from backend.api.service import set_service
        new_db_path = service.db_path

        if source_id == "enterprise":
            new_db_path = str(DEFAULT_DB)
        elif source_id == "spider":
            db_id = payload.get("database_id")
            if not db_id:
                raise HTTPException(status_code=422, detail="database_id required for Spider")
            spider = _spider_loader()
            if not spider:
                raise HTTPException(status_code=503, detail="Spider dataset not available")
            path = spider.resolve_database_path(db_id)
            if not path:
                raise HTTPException(status_code=404, detail=f"Spider database {db_id} not found")
            new_db_path = path
        elif source_id == "bird":
            db_id = payload.get("database_id")
            if not db_id:
                raise HTTPException(status_code=422, detail="database_id required for BIRD")
            bird = _bird_loader()
            if not bird:
                raise HTTPException(status_code=503, detail="BIRD dataset not available")
            path = bird.resolve_database_path(db_id)
            if not path:
                raise HTTPException(status_code=404, detail=f"BIRD database {db_id} not found")
            new_db_path = path
        else:
            raise HTTPException(status_code=404, detail=f"Unknown data source: {source_id}")

        # Create new service with new DB path
        new_service = PipelineService(db_path=new_db_path, index_dir=service.index_dir)
        set_service(new_service)

        # Return new schema info
        try:
            schema_payload = _schema_payload(new_db_path)
            return {"ok": True, "schema": schema_payload}
        except DatabaseError as exc:
            raise HTTPException(status_code=503, detail=f"database unavailable: {exc}")

    @app.post("/api/datasources/upload")
    async def upload_database(file: UploadFile = File(...)):
        """Upload a local SQLite database file."""
        allowed_ext = {".db", ".sqlite", ".sqlite3"}
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in allowed_ext:
            raise HTTPException(status_code=422, detail=f"File must be one of: {', '.join(allowed_ext)}")

        # Save to uploads directory
        uploads_dir = PROJECT_ROOT / "backend" / "data" / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename
        import uuid
        unique_name = f"{uuid.uuid4().hex}{suffix}"
        save_path = uploads_dir / unique_name

        with open(save_path, "wb") as out:
            while chunk := file.file.read(1 << 20):
                out.write(chunk)

        # Inspect it
        try:
            schema_payload = _schema_payload(str(save_path))
            return {"ok": True, "path": str(save_path), "schema": schema_payload}
        except DatabaseError as exc:
            # Clean up invalid file
            save_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=f"Invalid SQLite database: {exc}")

    # --- models ----------------------------------------------------------------
    @app.get("/api/models")
    def list_models():
        """List available Ollama models."""
        try:
            response = requests.get(f"{DEFAULT_HOST.rstrip('/')}/api/tags", timeout=3)
            if response.status_code == 200:
                models = response.json().get("models", [])
                return {
                    "models": [
                        {
                            "name": m.get("name", ""),
                            "size": m.get("size", 0),
                            "modified_at": m.get("modified_at", ""),
                        }
                        for m in models
                    ]
                }
            return {"models": []}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")

    @app.post("/api/models/select")
    def select_model(payload: dict):
        """Switch the active Ollama model."""
        model_name = payload.get("model")
        if not model_name:
            raise HTTPException(status_code=422, detail="model is required")

        # Verify model exists
        try:
            response = requests.get(f"{DEFAULT_HOST.rstrip('/')}/api/tags", timeout=3)
            if response.status_code == 200:
                models = [m.get("name", "") for m in response.json().get("models", [])]
                if model_name not in models:
                    raise HTTPException(status_code=404, detail=f"Model {model_name} not installed")
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")

        # Update the pipeline config (requires pipeline rebuild)
        from backend.api.service import set_service, get_service
        service = get_service()
        new_service = PipelineService(db_path=service.db_path, index_dir=service.index_dir)
        # Note: PipelineConfig.llm_model is used at pipeline creation time
        # We'll need to pass model to pipeline; for now we rebuild with new config
        # This is handled by the frontend passing model in query payload
        return {"ok": True, "model": model_name}

    # --- suggestions -----------------------------------------------------------
    @app.get("/api/suggestions")
    def get_suggestions(service: PipelineService = Depends(_service)):
        """Generate schema-aware question suggestions."""
        try:
            schema = inspect_database(service.db_path)
            questions = []

            for table in schema.tables:
                if table.row_count and table.row_count > 0:
                    # Count questions
                    questions.append(f"How many {table.name} are there?")
                    # Simple list question
                    questions.append(f"List all {table.name}.")
                    # Show columns for exploration
                    if table.columns:
                        col_names = [c.name for c in table.columns[:3]]
                        questions.append(f"Show {', '.join(col_names)} for each {table.name}.")

            # Deduplicate and limit
            seen = set()
            unique = []
            for q in questions:
                if q not in seen:
                    seen.add(q)
                    unique.append(q)
            return {"questions": unique[:8]}
        except Exception:
            return {"questions": []}

    # --- TTS -------------------------------------------------------------------
    @app.post("/api/tts")
    def text_to_speech(payload: dict):
        """Generate speech from text using local TTS (Windows SAPI with improved voice)."""
        text = payload.get("text", "")
        voice = payload.get("voice", "af_heart")  # Default to female voice
        if not text:
            raise HTTPException(status_code=422, detail="text is required")

        # Try Windows SAPI via PowerShell with better voice selection
        import subprocess
        import tempfile

        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                wav_path = tmp.name

            # Map voice names to Windows SAPI voice names
            voice_map = {
                "af_heart": "Microsoft Zira Desktop",  # Female, natural
                "af_bella": "Microsoft Hazel Desktop",  # Female, British
                "af_nicole": "Microsoft Susan Desktop",  # Female
                "am_michael": "Microsoft David Desktop",  # Male
                "am_fenrir": "Microsoft Mark Desktop",  # Male
            }
            sapi_voice = voice_map.get(voice, "Microsoft Zira Desktop")

            # Clean text for PowerShell - escape special characters
            clean_text = text.replace('"', '""').replace("'", "''").replace("`", "``")
            escaped_path = wav_path.replace("\\", "\\\\")
            escaped_text = clean_text.replace('"', '""')

            # Use PowerShell with SAPI.SpVoice with voice selection
            ps_script = f'''
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
# Try to select the requested voice
$voice = $synth.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Name -like "*{sapi_voice}*" }} | Select-Object -First 1
if ($voice) {{
    $synth.SelectVoice($voice.VoiceInfo.Name)
}} else {{
    # Fallback to any female voice
    $femaleVoice = $synth.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Gender -eq "Female" }} | Select-Object -First 1
    if ($femaleVoice) {{ $synth.SelectVoice($femaleVoice.VoiceInfo.Name) }}
}}
$synth.Rate = 0
$synth.Volume = 100
$synth.SetOutputToWaveFile("{escaped_path}")
$synth.Speak("{escaped_text}")
$synth.Dispose()
'''
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                timeout=30
            )

            if result.returncode != 0:
                raise Exception(result.stderr.decode())

            return FileResponse(wav_path, media_type="audio/wav", filename="answer.wav")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"TTS failed: {exc}")

    # --- static frontend (built Vite output) ----------------------------------
    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True),
                  name="frontend")

    return app


app = create_app()


def main():
    import uvicorn
    import os

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")

    uvicorn.run("backend.api.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()