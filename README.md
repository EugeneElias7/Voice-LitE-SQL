# Voice-LitE-SQL

A local, research-oriented **speech-to-SQL** system: speak a natural-language
question, and the system transcribes it (Whisper), normalizes ASR errors
against the database vocabulary (phonetic normalization), retrieves the
relevant schema (ChromaDB), generates SQL with a small local LLM
(qwen2.5-coder via Ollama), and executes it safely against SQLite.

The core research contribution is **database-aware phonetic normalization**:
correcting speech-recognition errors by grounding them in the actual schema
terms of the database being queried.

> Research question: _Does database-aware phonetic normalization improve
> execution accuracy in local speech-to-SQL systems under ASR noise?_

---

## Roadmap

Built level by level. Every level is verified and **frozen** before the next
one starts: `IMPLEMENT -> UNIT TEST -> INTEGRATION TEST -> MEASURE ->
DOCUMENT -> FREEZE -> NEXT LEVEL`.

| Level | Module | Main Technology | Status |
|------:|--------|-----------------|--------|
| L0 | Environment | Python / Ollama | ✅ DONE |
| L1 | Custom Database | SQLite | ✅ DONE |
| L1 | Question Dataset | JSON | ✅ DONE |
| L2 | Schema Inspector | SQLite / Python | ✅ DONE |
| L3 | Text -> SQL | Qwen / Ollama | ✅ DONE |
| L4 | SQL Execution | SQLite | ✅ DONE |
| L5 | Speech Recognition | Whisper | ✅ DONE |
| L6 | Phonetic Normalization | RapidFuzz / Jellyfish | ✅ DONE |
| L7 | Schema Retrieval | ChromaDB / Embeddings | ✅ DONE |
| L8 | Self-Correction | Qwen + SQLite | ✅ DONE |
| L9 | Full Pipeline | FastAPI | ✅ DONE |
| L11 | Interactive Frontend | React / FastAPI | ✅ DONE |
| L10 | Evaluation | Metrics | ✅ DONE |
| L10 | Spider / Spoken Spider / BIRD | Benchmarks | ✅ Spider dev done |

## Current status

- **L0 Environment** — setup scripts, `requirements.txt`, `OLLAMA_MODELS`
  pointing at `C:\AI_Models`.
- **L1 Data Foundation** — `enterprise.db` (7 tables, 9,295 rows, fixed
  `SEED = 42`), `schema.json`, `questions.json` (50 Q-SQL pairs),
  `corrupted_queries.json` (20 ASR-noise pairs), seed generator, tests.
- **L2 Schema Understanding** — `connection.py` (safe SQLite connection with
  FK enforcement) + `schema_inspector.py` (auto-discovers tables, columns,
  types, PKs, FKs of any SQLite database; CLI included).
- **L3 Text -> SQL baseline** — `llm/` package: Ollama HTTP client
  (`ollama_client.py`), schema-driven prompt builder (`prompts.py`), and the
  pipeline `generate_sql()` with robust SQL extraction + read-only validation
  (`sql_generator.py`). Model: `qwen2.5-coder:1.5b` (stored in `models/`).
- **L4 SQL Execution + baseline** — `executor.py` (genuinely read-only
  execution, `mode=ro`, rejects destructive SQL/multi-statements) +
  `evaluation/` (normalized semantic comparison, per-question evaluation,
  metrics by category) + `scripts/l4_evaluator.py` (real-model baseline
  experiment, JSON reports in `evaluation/results/`).
- **L5 Speech / ASR** — `asr/` package: local Whisper engine
  (`whisper_engine.py`, openai-whisper or faster-whisper, no auto-download,
  structured `TranscriptionResult`), spoken manifest + WER
  (`models.py`), recording prep (`scripts/record_audio.py`) and evaluation
  (`scripts/l5_asr.py`, audio -> transcript -> L3 -> L4).
- **L6 Database-Aware Phonetic Normalization** — `phonetics/` package:
  `algorithms.py` (Soundex/Metaphone/NYSIIS + Jaro-Winkler/Levenshtein via
  jellyfish+rapidfuzz), `vocabulary.py` (schema-grounded terms built from
  **any SQLite database via the L2 Schema Inspector** — never hardcoded),
  `normalizer.py` (token correction with similarity + phonetic-encoding
  gates, plural-aware tie-breaking, multi-word column merge; every examined
  token produces a `TokenDecision` record: original/replacement/confidence/
  applied/strategy/reason/scores), `scripts/l6_evaluator.py` (token-level
  metrics: precision/recall/accuracy/unchanged-token-rate, ablations,
  optional `--with-llm` real-model A/B). The L6 config is **frozen** in
  `NormalizerConfig` defaults: it was tuned once on the 20-pair development
  set (`corrupted_queries.json`) and is never re-tuned per run or per
  dataset — real runs (e.g. `scripts/l5_asr.py --manifest`) are
  deterministic single passes, with `--no-phonetic` as the only ablation
  switch.
- **Next: L7 Schema Retrieval** — ChromaDB embeddings (relevant tables +
  columns per question, instead of always passing the full schema).

## Project structure

```
Voice-LitE-SQL/
├── backend/
│   ├── database/
│   │   ├── models.py          # schema definition (single source of truth)
│   │   ├── seed.py            # python -m backend.database.seed
│   │   ├── connection.py      # safe SQLite connection (FK enforced)
│   │   ├── schema_inspector.py# python -m backend.database.schema_inspector <db>
│   │   ├── executor.py        # read-only SQL execution (mode=ro, safe)
│   │   └── data/enterprise.db # generated SQLite database
│   ├── asr/
│   │   ├── whisper_engine.py  # local Whisper engine (no auto-download)
│   │   └── models.py          # TranscriptionResult, spoken manifest, WER
│   ├── phonetics/
│   │   ├── algorithms.py     # Soundex/Metaphone/NYSIIS, Jaro-Winkler/Levenshtein
│   │   ├── vocabulary.py     # schema-grounded term vocabulary (+ambiguity)
│   │   └── normalizer.py     # DatabaseAwareNormalizer (frozen config)
│   ├── evaluation/
│   │   ├── evaluator.py       # per-question evaluation (semantic comparison)
│   │   └── metrics.py         # overall + category metrics
│   ├── llm/
│   │   ├── ollama_client.py   # local Ollama HTTP client (configurable host/model)
│   │   ├── prompts.py         # schema -> SQL prompt builder
│   │   └── sql_generator.py   # question -> SQL pipeline + extraction + validation
│   ├── datasets/
│   │   └── custom/
│   │       ├── schema.json           # auto-written by seed.py
│   │       ├── questions.json        # 50 Q-SQL pairs
│   │       ├── corrupted_queries.json# 20 ASR-noise pairs
│   │       └── spoken/
│   │           ├── manifest.json     # question -> reference text -> audio
│   │           └── audio/            # recorded WAVs (manual, never fabricated)
│   └── tests/
│       ├── test_level1.py            # Level 1 verification
│       ├── test_level2.py            # Level 2 verification
│       ├── test_level3.py            # Level 3 verification (Ollama mocked)
│       └── test_level4.py            # Level 4 verification
├── evaluation/
│   └── results/                # JSON baseline reports (l4_report.json)
├── models/                     # local Ollama model storage (qwen2.5-coder:1.5b)
├── scripts/                    # environment setup (Windows / Mac / Linux)
├── docs/
├── assets/
└── requirements.txt
```

## Setup (Windows)

1. Run the environment setup as **Administrator**:
   `powershell -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1`
2. Completely quit Ollama from the system tray, restart it, then in a fresh
   terminal: `ollama pull qwen2.5-coder:1.5b` (downloads to `C:\AI_Models`).
3. Verify: `python --version`, `node -v`, `ollama --version`.

## Level 1 usage

```powershell
# Rebuild the database + schema.json (identical every time, SEED = 42)
python -m backend.database.seed

# Run all Level 1 tests
python -m pytest backend/tests -v
```

Expected seed output: tables with row counts
`locations 30 / departments 15 / employees 500 / customers 1000 /
products 250 / sales 5000 / orders 2500`.

## Level 6 usage (phonetic normalization)

```powershell
# 1) Offline metrics on the 20-pair development set (not the final
#    evaluation set). Vocabulary is built from the database via the L2
#    Schema Inspector; --schema overrides with schema.json.
#    Report -> evaluation/results/l6_report.json
python scripts/l6_evaluator.py
python scripts/l6_evaluator.py --schema backend/datasets/custom/schema.json

# 2) Same, plus the real-model A/B experiment (requires Ollama running):
#    does normalization recover the original answer under ASR noise?
python scripts/l6_evaluator.py --with-llm

# 3) Voice pipeline with the L6 stage (frozen config) wired in:
#    record audio first, then run; --no-phonetic is the ablation switch
python scripts/record_audio.py
python scripts/l5_asr.py --manifest
python scripts/l5_asr.py --manifest --no-phonetic

# 4) Level 6 tests
python -m pytest backend/tests/test_level6.py -v
```

Using the normalizer directly:

```python
from backend.phonetics import DatabaseAwareNormalizer, DatabaseVocabulary

vocabulary = DatabaseVocabulary.from_database("backend/data/enterprise.db")  # L2 Schema Inspector
normalizer = DatabaseAwareNormalizer(vocabulary)   # frozen config
result = normalizer.correct("Show employee celery")
# result.text         -> 'Show employee salary'
# result.corrections  -> [Correction(token='celery', corrected='salary', kind='column',
#                        reason='phonetic', scores={'jaro_winkler': 0.67, 'levenshtein_ratio': 0.5}, ...)]
# result.decisions    -> one TokenDecision per examined token (applied or not):
#                        {original, replacement, confidence, applied, strategy, reason, scores, candidate}
```

## Data hierarchy

```
                 DATA
                   │
        ┌──────────┴──────────┐
        │                     │
   DEVELOPMENT             RESEARCH
        │                     │
        ▼                     ▼
  Custom Dataset          Spider 1.0
  (enterprise.db)         Spoken Spider
  (controlled tests)      BIRD
```

- **Development** — `enterprise.db` + hand-curated questions. Controlled
  environment: any failure can be traced to a single stage (ASR, phonetics,
  retrieval, LLM, execution).
- **Research** — Spider / Spoken Spider / BIRD are *evaluation benchmarks
  only* (L10). They are never the application database.

## Dataset specs

| File | Contents |
|------|----------|
| `schema.json` | 7 tables, columns only (flat format, roadmap style) |
| `questions.json` | 50 pairs: 10 SELECT, 10 WHERE, 10 JOIN, 5 GROUP BY, 5 ORDER BY, 5 aggregate, 5 complex |
| `corrupted_queries.json` | 20 pairs `{original, corrupted, target}`; targets are real schema terms (`sales -> sails`, `salary -> celery`, `revenue -> avenue`, ...) — **development/tuning set only**, not part of the real-dataset measurement |

## L10 benchmark results — Spider dev (frozen L9 pipeline)

Full Spider dev split (1,034 questions / 20 databases) run through the frozen
L9 pipeline per `db_id`. Report: `evaluation/results/l10_spider_dev_report.json`.

| Metric | Value |
|--------|-------|
| Total questions | 1,034 |
| **Execution accuracy** | **39.85%** (412/1,034) |
| Generation success rate | 99.81% |
| Execution success rate | 67.6% |
| SQL execution error rate | 32.4% |
| Median pipeline latency | 6.7 s / question |
| Correction rescued / harmed | 35 / 0 |

Spider is a research-only benchmark (never the application database); the
Enterprise-controlled experiments remain the tuning targets
(L4 40% / L7 36% / L8 48% / L8.1 54% / L9 text 58% — frozen).

Run instructions:

```bash
python scripts/l10_spider_eval.py --offset 0 --limit 150   # chunked, incremental
python scripts/l10_spider_eval.py --offset 5 --question-timeout 300
python scripts/l10_spider_eval.py --merge
```

Chunks resume from `evaluation/results/l10_spider_dev_progress.jsonl`; a
per-question `--question-timeout` guards against single-session hangs.

## Planned experiments (L10)

| System | SQL Accuracy | Execution Accuracy | Correction Accuracy | Avg Latency |
|--------|-------------|--------------------|---------------------|-------------|
| Text -> SQL (baseline) | ? | ? | — | ? |
| Voice -> SQL | ? | ? | — | ? |
| Voice + Phonetic | ? | ? | ? | ? |
| + Schema Retrieval | ? | ? | ? | ? |
| + Self-Correction | ? | ? | ? | ? |

## L11 — Interactive Frontend

The L11 frontend is a **product-style AI database assistant** — answer-first,
with engineering detail moved behind progressive disclosure. It runs the
**real frozen L9 pipeline**; nothing is mocked or hardcoded.

**Product flow (primary UI)**

1. **Composer is the hero** — "Ask your database anything." A large input
   (`Ask →`) plus **real microphone** (`Ask with your voice`) with a live
   `Listening… ● 00:03` state. Example questions ("Try asking") fill the
   input but never auto-run.
2. **Friendly pipeline** — a single row of user steps derived from the real
   stage state: `🎙 You asked → 🧠 Understanding → 🔎 Finding data →
   🤖 Creating SQL → 🛡 Checking → ⚡ Running → ✨ Answer`. Each shows
   waiting / working / ✓ / ✕ as the actual backend stages complete.
3. **Answer first** — the result is the largest element (big KPI or clean
   table + pagination + row count), with a `Real database result · executed
   in X` note. Failures render an honest "We couldn't get that answer" card.
4. **Understanding** — a concise chip row (intent + entities + concepts) with
   **no raw scores** in the primary view.
5. **How did you get this answer?** — expandable: Understanding → Data found
   → Relationships → SQL created → Safety check → Database.
6. **Technical details** — a tabbed modal (Overview / NLP / Schema / SQL /
   Execution / Correction) holding all L6/L7/L8/L8.1 internals: intent,
   entity links, phrase scores, reranking, relationship filtering, retrieval
   items with scores/distances, validation issues, correction attempts.

Supporting UI: compact **DATABASE** card (`7 tables · 9,295 rows` →
"Explore schema" opens a drawer explorer), a **System ready** pill that
opens a per-component health tray, and clean **Recent questions** history
(localStorage) that restores full results on click.

**Architecture**

- **Backend** (`backend/api/`): FastAPI layer added on top of the frozen
  pipeline. It is the single entry point; the browser never executes SQL.
- **Frontend** (`frontend/`): React 18 + Vite 5 + TypeScript, dark-first,
  desktop-first. No UI framework — hand-built CSS.
- Queries stream **real per-stage progress** via SSE using the actual
  `PipelineTimer` inside the frozen pipeline (runtime instrumentation only;
  frozen code untouched). Every displayed latency, transcript, intent, SQL,
  schema item, correction attempt and status comes from the real
  `PipelineResult` — the UI is a visualization of the backend, not a mock.

**Endpoints**

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Liveness |
| `/api/status` | GET | Component health (ollama / whisper / chroma / db / schema) |
| `/api/schema` | GET | L2 schema inspector output + live row counts |
| `/api/demo-questions` | GET | Demo questions (from `questions.json`) |
| `/api/query` | POST | Text → real L9 pipeline |
| `/api/voice-query` | POST | Audio → real Whisper → real L9 pipeline |
| `/api/query/stream` | POST | Text with SSE live per-stage progress |
| `/api/voice-query/stream` | POST | Audio with SSE live per-stage progress |

**Frontend features**

- Hero composer: `Enter` to ask, `Shift+Enter` newline; hold-to-speak mic
  with permission-denied and no-mic fallbacks.
- Friendly 7-step flow driven by real backend stage state.
- Answer-first result (KPI hero or data table with pagination + row count).
- Understanding card (intent + entity/concept chips, no scores).
- "How did you get this answer?" progressive-disclosure section.
- Technical-details modal (Overview / NLP / Schema / SQL / Execution /
  Correction) with all L5–L8.1 internals.
- Recent-questions history (localStorage) with full-result restore.
- Schema explorer drawer + compact database card + system health tray.

**Run it**

```
# terminal 1 — backend
python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000

# terminal 2 — frontend (dev server)
npm --prefix frontend run dev        # open http://localhost:5173
```

Or, once built (`npm --prefix frontend run build`), the backend serves the
dashboard at `http://127.0.0.1:8000` automatically.

**Tests**

- Backend: existing suite plus `backend/tests/test_level11_api.py` (endpoint,
  SSE stream, pipeline-error, progress-hook restore tests).
- Frontend: `npm --prefix frontend run test` (Vitest + jsdom).

Author: Eugene Elias
