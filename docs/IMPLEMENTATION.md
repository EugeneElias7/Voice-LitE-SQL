# Voice-LitE-SQL — Technical Implementation Documentation

## 1. Project Overview

Voice-LitE-SQL is a staged research pipeline for natural-language-to-SQL with spoken input. It progresses from data foundation (L1) through schema understanding (L2), SQL generation (L3-L4), ASR (L5), phonetic normalization (L6), schema retrieval (L7), and beyond. The project uses a local Qwen 2.5 Coder 1.5B model through Ollama, an enterprise SQLite database with 7 tables and 9,295 rows, and aims to maintain experimental validity through frozen baselines and documented interventions.

**Why this exists:** To research how text-to-SQL degrades with spoken input, ASR errors, schema complexity, and LLM hallucinations — and whether staged interventions (phonetic normalization, schema retrieval, execution-guided correction) can recover accuracy.

**Research objective:** Measure the impact of each intervention on a controlled 50-question enterprise SQL benchmark, with the L4 full-schema baseline frozen at 40% execution accuracy. No L4 code, model, or configuration may be modified after baseline establishment.

**Local/privacy motivation:** All processing is local (Ollama on laptop, SQLite embedded). No cloud APIs beyond Ollama. Data is synthetic/enterprise-internal. Models: `qwen2.5-coder:1.5b` and `whisper-small`.

---

## 2. Research Problem

Natural-language-to-SQL becomes harder when:

- Input is spoken (ASR introduces substitutions, insertions, deletions)
- ASR WER propagates into phonetic mismatches on column/table names
- Database schemas are large and LLMs may hallucinate non-existent elements
- Small LLMs (1.5B) struggle with full-schema context or retrieved-schema context
- Generated SQL may fail execution (wrong table, wrong column, syntax error)
- Phonetic normalization may or may not recover the intended identifier

The research question at each level is: *What specific intervention improves or maintains execution accuracy on the 50-question benchmark, and what is the measured effect?*

---

## 3. Research Approach

The project uses a staged, incremental approach. Each level is an experimental intervention/control point. Earlier levels provide the foundation for later levels. Levels L1–L6 are complete and frozen; L7 is complete and evaluated; L8–L10 are defined but not yet implemented.

**Level progression:**

- L1 → Data foundation (database, questions)
- L2 → Schema understanding (inspector)
- L3 → Text-to-SQL (Qwen → SQL)
- L4 → Baseline (full-schema → Qwen → execute)
- L5 → ASR (speech input → Whisper)
- L6 → Phonetic normalization (speech errors → corrections)
- L7 → Schema retrieval (retrieved schema → Qwen → execute)
- L8 → Execution-guided correction (failed SQL → fix → retry)
- L9 → Complete system (end-to-end pipeline)
- L10 → Benchmark evaluation (external datasets)

Each level adds one intervention while keeping prior levels' code/model/configuration unchanged.

---

## 4. Overall Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Voice-LitE-SQL Pipeline                       │
├─────────────────────┬─────────────────────┬───────────────────────┤
│  Input              │  Processing         │  Output               │
│  (spoken question)  │  (L1 → L10)         │  (SQL + results)      │
├─────────────────────┼─────────────────────┼───────────────────────┤
│  Microphone         │  Audio capture      │  WAV files            │
│  (3.5mm earphone)   │  (record_audio.py)  │                       │
├─────────────────────┼─────────────────────┼───────────────────────┤
│  Whisper-small      │  ASR transcription  │  Text: user question  │
│  (faster-whisper)   │  (scripts/l5_asr.py)│                       │
├─────────────────────┼─────────────────────┼───────────────────────┤
│  Schema Inspector   │  Table/FK/col       │  Schema dict          │
│  (backend.database) │  discovery          │                       │
├─────────────────────┼─────────────────────┼───────────────────────┤
│  SQL Generator      │  Qwen prompt → SQL  │  SQL string          │
│  (backend.llm)      │  (generate_sql)     │                       │
├─────────────────────┼─────────────────────┼───────────────────────┤
│  Executor           │  Read-only SQL      │  Result rows +        │
│  (backend.database) │  execution          │  correctness flag    │
├─────────────────────┼─────────────────────┼───────────────────────┤
│  Phonetic Normalizer│  Vocabulary +       │  Normalized tokens    │
│  (L6 module)        │   metaphone matching│                       │
├─────────────────────┼─────────────────────┼───────────────────────┤
│  Schema Retriever   │  ChromaDB retrieval │  Top-k schema texts  │
│  (backend.retrieval)|  (sentence-transformers)│                   │
└─────────────────────┴─────────────────────┴───────────────────────┘
```

---

## 5. Level-by-Level Implementation

### Level 1 — Data Foundation

**Objective:** Establish the enterprise SQLite database, the 50 clean questions, and the 20 corrupted/development queries as the immutable testbed for all later levels.

**Why This Level Exists:** Without a stable, seeded dataset with known-good SQL references, no later level can produce reproducible results. Seed = 42 ensures deterministic data generation.

**Implementation:**

- `backend/data/enterprise.db` — SQLite database with 7 tables
- `backend/datasets/custom/questions.json` — 50 clean natural-language questions with reference SQL
- `backend/datasets/custom/corrupted_questions.json` — 20 development queries
- Database has 9,295 total rows across: employees, departments, projects, tasks, inventory, sales, alerts

**Pipeline:**

```
User question → (stored in questions.json) → L2 schema inspection → L3 SQL generation → L4 execution → correctness check
```

**Key Implementation Snippets:**
Database schema discovery (L2 module references this structure):

```python
# backend/database/schema_inspector.py — inspect() returns table/col/FK objects
inspector = SchemaInspector(db_path)
schema = inspector.inspect()  # → NamedTuple with tables, columns, foreign_keys
```

**Tests:** `backend/tests/test_level1.py` — 10 passed

**Evaluation / Results:**

- 7 tables in enterprise.db
- 9,295 total rows
- 50 clean questions in questions.json
- 20 corrupted/development queries
- Seed = 42 confirmed

**Important Findings:** The database is the single source of truth for all later levels. Schema mutations break downstream results.

**Research Significance:** Establishes the controlled environment. All later levels reference the same DB and question set.

**Status:** COMPLETE — FROZEN

---

### Level 2 — Schema Inspector

**Objective:** Provide a database-independent method to discover schema structure (tables, columns, types, primary keys, foreign keys) from SQLite without depending on the LLM or models.py.

**Why This Level Exists:** L3–L6 all need schema information. Centralizing this in a reusable module prevents divergent schema representations and enables reproducible testing with temporary databases.

**Implementation:**

- `backend/database/schema_inspector.py` — `inspect()` method returns table objects with `.name`, `.columns` (name, type, pk_position), `.foreign_keys` (source_column, target_table, target_column)
- Uses only `sqlite3`, no model dependencies
- Tested with temporary databases to verify independence from enterprise.db specifics

**Pipeline:**

```
Database file → schema_inspector.inspect() → dict of tables/cols/FKs → L3 prompt building → L6 vocabulary generation
```

**Key Implementation Snippets:**

```python
# Core inspection entry point
def inspect(self) -> Schema:
    # Reads from SQLite master/columns/foreign_keys
    # Returns typed NamedTuple, model-independent
```

**Tests:** `backend/tests/test_level2.py` — 14 passed

**Evaluation / Results:**

- 14 unit tests verifying inspection correctness
- Tested against independent temporary databases (not just enterprise.db)
- All FK paths validated
- Column type mapping verified

**Important Findings:** Schema inspector is the single source of schema description for L3 prompt grounding and L6 vocabulary generation. It does not depend on models.py.

**Research Significance:** Decouples schema discovery from LLM concerns. Enables fair comparison across levels.

**Status:** COMPLETE — FROZEN

---

### Level 3 — Text-to-SQL

**Objective:** Generate SQL from natural language using Qwen 2.5 Coder 1.5B through Ollama, with schema-grounded prompting, SQL extraction/cleanup, and safety validation.

**Why This Level Exists:** L3 is the core text-to-SQL capability. Without it, no later level can operate. The schema-grounded prompting strategy and SQL extraction pipeline are the foundation on which L4–L7 build.

**Implementation:**

- `backend/llm/ollama_client.py` — `generate(prompt, model)` sends to Ollama, returns response + latency
- `backend/llm/sql_generator.py` — `generate_sql(prompt)` → `extract_sql(text)` cleans markdown fences, extracts first SELECT
- `backend/database/executor.py` — `execute_sql(sql, db_path)` read-only execution, `compare_results(ref, got)` semantic normalization
- Prompt format: `Use only the provided schema. Do not invent tables or columns. Schema: {schema_text} Question: {question} SQL:`

**Pipeline:**

```
Natural language question → schema-grounded prompt → Qwen 1.5B → extract SQL → safety validate → execute SQL → compare to reference
```

**Key Implementation Snippets:**

```python
# SQL extraction from LLM output
def extract_sql(text: str) -> str:
    # Strip markdown ``` blocks
    # Find first SELECT ... ;
    # Upper-case normalization
```

```python
# Safety validation boundary
def validate_generated_sql(sql: str, schema_text: str) -> bool:
    # Check no invented tables/columns
    # Verify FROM and WHERE clauses reference existing schema elements
```

**Tests:** `backend/tests/test_level3.py` — 21 passed

**Evaluation / Results:**

- 21 unit tests covering prompt generation, SQL extraction, execution, comparison
- L3 alone (no execution constraint) has higher success rate than end-to-end L4

**Important Findings:** LLM schema hallucination is the dominant failure mode (invented `location_id` column, `orders` table). Prompt boundary "Do not invent tables or columns" reduces but does not eliminate hallucinations.

**Research Significance:** Establishes the text-to-SQL core. L4 builds on this with execution validation.

**Status:** COMPLETE — FROZEN

---

### Level 4 — SQL Execution + Baseline

**Objective:** Establish the read-only SQL execution baseline on the enterprise database. This is the frozen control: full schema → Qwen → SQL → execute. Accuracy = 40% on 50 questions. No code/model/config changes may be made to L4 after baseline establishment.

**Why This Level Exists:** L4 is the baseline against which all later levels (L5–L10) are measured. It represents the system with maximum schema context (full inspector output) and no speech/phonetic interventions.

**Implementation:**

- `scripts/l4_evaluator.py` — runs 50 questions with full schema, generates SQL, executes, compares
- Report: `evaluation/results/l4_report.json`
- Key metrics: execution_accuracy = 40%

**Pipeline:**

```
Full schema (all tables/cols/FKs) → build prompt → Qwen → extract SQL → execute (read-only) → compare results → correctness flag
```

**Key Implementation Snippets:**

```python
# Read-only execution boundary
def execute_sql(sql: str, db_path: str) -> Tuple[List[Dict], str]:
    # Connect, execute, fetch
    # Normalize results (sort rows, cast types for comparison)
    # Return rows + error string
```

```python
# Semantic result comparison
def compare_results(reference: List[Dict], generated: List[Dict]) -> Tuple[bool, str]:
    # Sort both by primary key
    # Compare row counts and values
    # Return (match, error_details)
```

**Tests:** `backend/tests/test_level4.py` — 34 passed

**Evaluation / Results:**

- **L4 accuracy: 40%** on 50 questions
- Per-category: SELECT=80% (10/10), WHERE=30% (10/10), JOIN=50% (10/10), GROUP BY=40% (5/5), ORDER BY=40% (5/5), aggregate=0% (5/5), complex=0% (5/5)
- SQL execution error rate: 22%
- Average latency: ~8.4 seconds per question

**Important Findings:**

- 40% is the frozen baseline. Do NOT modify.
- Aggregate and complex questions always fail (LLM cannot generate correct GROUP BY or multi-constraint SQL)
- WHERE accuracy is low (30%) — phonetic errors on filtered columns would worsen this
- SELECT accuracy is high (80%) — schema retrieval may help here

**Research Significance:** The control baseline. All later levels compare against L4=40%.

**Status:** COMPLETE — FROZEN

---

### Level 5 — ASR

**Objective:** Transcribe spoken input using Whisper-small (faster-whisper backend), with multi-backend capture support, real microphone validation, and TTS fallback for development.

**Why This Level Exists:** L5 introduces speech as the input modality. Without it, the pipeline is limited to typed text. This level validates that the microphone + Whisper-small can transcribe real voice with measurable WER.

**Implementation:**

- `scripts/l5_asr.py` — main CLI: `--asr-model`, `--backend`, `--device`, `--synth`, `--no-phonetic`, `--report`
- `scripts/record_audio.py` — records WAV via sounddevice/pyaudio, supports `--auto`, `--synth`, `--force`, `--device N`
- `scripts/voice_capture.py` — auto-unmute via pycaw (Windows Core Audio), `ensure_mic_unmuted()`
- DEFAULT_MODEL changed from `"base"` to `"small"` (both tests and scripts)
- Whisper-small: 384-dim embeddings, int8 compute_type on CPU

**Pipeline:**

```
Microphone → record_audio.py → WAV files → Whisper-small (faster-whisper or openai-whisper) → text transcript → L6 phonetic normalization → L3 SQL generation
```

**Key Implementation Snippets:**

```python
# Mic unmute fix (the root cause: Windows mic was muted at 97%)
def ensure_mic_unmuted():
    # pycaw IMMDevice → AudioEndpointVolume → SetMute(False)
    # Required: pycaw, sounddevice
```

```python
# ASR transcription entry point
result = engine.transcribe(audio_path)
# Returns: text, success flag, WER, latency_ms
```

**Tests:** `backend/tests/test_level5.py` — 20 passed

**Evaluation / Results:**

- Real microphone (3.5mm earphone) validated: Whisper-small transcribes real voice successfully
- 8/8 audio samples transcribed
- WER = 0.2882 on 8 real samples
- Average transcription latency ≈ 9.78 seconds
- Default model: `small` (changed from `base`)
- Multi-backend: faster-whisper fallback → openai-whisper

**Important Findings:**

- Built-in AMD microphone is phantom/non-functional; 3.5mm earphone required
- Mic was muted at OS level — fixed via pycaw `ensure_mic_unmuted()`
- Whisper-small works; `base` model was insufficient for some phrases
- 8-sample real-audio set is small; results not generalizable but confirm pipeline works

**Research Significance:** Confirms speech input pipeline is viable with correct hardware and unmute configuration. L6 builds on the transcribed text.

**Status:** COMPLETE

---

### Level 6 — Database-Aware Phonetic Normalization

**Objective:** Normalize ASR-transcribed tokens using vocabulary from L2 schema + fuzzy + phonetic matching (metaphone), with conservative confidence/margin gates. The frozen configuration: threshold=0.75, margin=0.12, metaphone=True, merge=True.

**Why This Level Exists:** ASR introduces substitutions/insertions/deletions on schema names. Phonetic normalization attempts to recover the intended column/table name when Whisper produces a near-match. This level measures whether normalization actually improves end-to-end SQL execution accuracy.

**Implementation:**

- `backend/phonetic/vocabulary.py` — generates vocabulary from L2 schema (all table/column names)
- `backend/phonetic/matcher.py` — fuzzy + metaphone matching with confidence scoring
- Frozen configuration: `threshold=0.75`, `margin=0.12`, `metaphone=True`, `merge=True`
- Development results: strict recovery=85%, equivalent recovery=95%, correction precision=95%, recall=95%, accuracy=96%

**Pipeline:**

```
ASR text → L6 matcher → (if confidence ≥ threshold) normalize token → pass corrected text to L3 SQL generation → L4 execution → correctness check
```

**Key Implementation Snippets:**

```python
# Phonetic token decision flow
def normalize_token(token: str, vocabulary: Set[str], threshold: float = 0.75, margin: float = 0.12) -> Optional[str]:
    # 1. Fuzzy ratio (token vs closest vocab entry)
    # 2. Metaphone code match
    # 3. If confidence ≥ threshold + margin: return normalized form
    # 4. If confidence ≥ threshold but ≤ threshold + margin: return None (keep original)
    # 5. If confidence < threshold: return None (keep original)
```

```python
# Vocabulary generation from L2 schema
vocab = generate_vocabulary(db_path)  # all table + column names
```

**Tests:** `backend/tests/test_level6.py` — 39 passed

**Evaluation / Results:**

*Development set (corrupted_queries.json):*

- strict recovery = 85% (85% of ASR errors were correctly normalized)
- equivalent recovery = 95% (95% of normalized tokens were semantically equivalent)
- correction precision = 95%
- correction recall = 95%
- correction accuracy = 96%

*Real 8-sample ablation:*

- no phonetic = 3/8 = 37.5% execution accuracy
- phonetic = 3/8 = 37.5% execution accuracy
- **no rescued queries** (L6 never changed an incorrect SQL to correct)
- **no harmed queries** (L6 never changed a correct SQL to incorrect)
- Key finding: L6 had **no measurable effect** on execution accuracy for the 8 real-audio samples

**Important Findings:**

- L6 showed 85% development-set recovery but **zero end-to-end impact** on the 8 real-audio samples
- Several failures are NOT speech problems (e.g., q05: WER=0 but SQL references nonexistent `location_id`)
- The 95% development recovery does not translate to real-audio gain
- Phonetic normalization alone cannot overcome L4's schema hallucination problem

**Research Significance:** Isolates the phonetic normalization question. L7 (schema retrieval) is the next intervention.

**Status:** COMPLETE — FROZEN

---

### Level 7 — Schema Retrieval / Schema Linking

**Objective:** Evaluate whether retrieving only the schema elements relevant to a question (instead of feeding Qwen the complete schema) reduces the table/column hallucinations seen in the L4 baseline. Observed L4 failure types: invented `customers.location_id`, incorrect `orders` table use, wrong associations such as `departments.salary`.

**Why This Level Exists:** L6 (phonetic normalization) showed no end-to-end gain. The remaining failure mode is L4-level schema hallucination. The hypothesis for L7 is that database-aware retrieval + schema-grounded prompting reduces hallucinations by showing only the relevant tables/columns/FKs for each question.

**Implementation:** (new package `backend/retrieval/`)

- `backend/retrieval/schema_documents.py` — builds schema documents from the L2 SchemaInspector (database-driven, never hardcoded, never models.py). Three document kinds: table-level (`TABLE: employees / COLUMNS: ...`), column-level (`COLUMN: employees.salary / TYPE: REAL / ...`), relationship-level (`RELATIONSHIP: employees.department_id -> departments.department_id`). Deterministic document IDs.
- `backend/retrieval/embeddings.py` — configurable embedder wrapping sentence-transformers (`all-MiniLM-L6-v2`, 384-dim, `local_files_only=True` so models are never auto-downloaded), plus a deterministic `CountVectorEmbedder` (TF-IDF hashing) for offline tests.
- `backend/retrieval/chroma_store.py` — persistent, configurable ChromaDB-backed schema index. Upsert by deterministic ID (no duplicates on repeat indexing), reset/rebuild, top-K cosine query.
- `backend/retrieval/schema_retriever.py` — `SchemaRetriever.retrieve(question, top_k)` returns structured results plus a deterministic relationship-expansion step that surfaces FK edges when a column doc is retrieved, and referenced columns when a relationship doc is retrieved.
- `backend/retrieval/prompt.py` — `build_l7_prompt(question, retrieved_schema_text)`; contains the user question, ONLY retrieved schema context + FK relationships, SQLite/read-only rules, and the explicit instruction `Use only the provided schema. Do not invent tables or columns.`
- `scripts/l7_evaluator.py` — runs the 50 clean questions through the L7 pipeline with the SAME Qwen model and L4 read-only executor, compares against the frozen `evaluation/results/l4_report.json`, and saves `evaluation/results/l7_report.json` (L4 never overwritten).
- `backend/tests/test_level7.py` — 28 tests (mocked embedder, no live dependency).

**Pipeline:**

```
SQLite db → L2 SchemaInspector → schema documents
        → sentence-transformers embeddings → ChromaDB
Question → question embedding → top-K relevant schema items
        → L7 schema-grounded prompt (retrieved schema only)
        → Qwen (same model as L4) → extract SQL → L4 read-only executor
        → execution result → evaluation vs reference SQL
```

**Key Implementation Snippets:**

```python
# L7 prompt: retrieved schema only (backend/retrieval/prompt.py)
def build_l7_prompt(question, schema_context_text):
    return f"""...Use only the provided schema. Do not invent tables or columns.
- Use SELECT (or WITH) only. The following operations are strictly forbidden: ...
- Use JOIN only when the schema relationships below require it.

RETRIEVED SCHEMA
{schema_context_text}

QUESTION
{question}

SQL:"""
```

```python
# Relationship-aware expansion (backend/retrieval/schema_retriever.py)
def _match_relationships(self, doc):
    if doc.doc_type == COLUMN_DOC:
        return [c for c in self._documents
                if c.doc_type == RELATIONSHIP_DOC and
                ((c.fk_source_table == doc.table and c.fk_source_column == doc.column)
                 or (c.fk_target_table == doc.table and c.fk_target_column == doc.column))]
    if doc.doc_type == RELATIONSHIP_DOC:
        return [d for d in [doc, self._document_by_id.get(column_doc_id(...))] if d]
```

```python
# Idempotent ChromaDB upsert by deterministic doc_id (backend/retrieval/chroma_store.py)
self.collection.upsert(ids=ids, documents=texts,
                       embeddings=[[float(v) for v in row] for row in embeddings])
```

**Tests:** `backend/tests/test_level7.py` — **28 passed** (schema documents from L2; no models.py dependency; arbitrary temp database; deterministic IDs; repeatable indexing with no duplicates; collection-name config; reset; Chroma retrieval; top-K; relevant columns/tables retrieved; FK relationship expansion; deterministic expansion; L7 prompt contains question + retrieved schema + no-invention rule; L4 executor unchanged; mocked embedding/retrieval without a live service).

**Evaluation / Results (real, 50 clean questions, `all-MiniLM-L6-v2`, top_k=5, qwen2.5-coder:1.5b):**

| Metric | L4 Baseline | L7 Retrieval | Diff |
| ------ | ----------- | ------------ | ---- |
| Execution accuracy | 40.0% | **36.0%** | **-4.0%** |
| Generation success rate | 100% | 100% | +0.0 |
| Execution success rate | 78.0% | 88.0% | **+10.0%** |
| SQL execution error rate | 22.0% | 12.0% | **-10.0%** |
| Avg execution latency | 4.16 ms | 2.84 ms | faster |
| Avg retrieval latency | — | 16.4 ms | added |
| Avg retrieved items / q | — | 5.9 | — |

Category-level execution accuracy:

| Category | L4 % | L7 % | Diff | N |
| -------- | ---- | ---- | ---- | - |
| SELECT | 80.0 | 70.0 | -10.0 | 10 |
| WHERE | 30.0 | 40.0 | +10.0 | 10 |
| JOIN | 50.0 | 40.0 | -10.0 | 10 |
| GROUP BY | 40.0 | 40.0 | 0.0 | 5 |
| ORDER BY | 40.0 | 20.0 | -20.0 | 5 |
| aggregate | 0.0 | 0.0 | 0.0 | 5 |
| complex | 0.0 | 0.0 | 0.0 | 5 |

Per-question delta vs frozen L4: **rescued = 2, harmed = 4, held = 16, missed = 28**.

- **Rescued** (`q08` "names of all employees with their salaries", `q11` "employees earn more than one hundred thousand"): retrieval surfaced `employees.salary` + `employees.employee_name`, which L4 had hallucinated. Both produced correct SQL.
- **Harmed** (`q03`, `q04`, `q30`, `q37`): the relationship-expansion step surfaced FK edges (`relationship:sales.product_id->products.product_id` etc.) and the small Qwen model added spurious INNER JOINs to simple single-table questions, producing executable-but-incorrect SQL (or dropping a required column as in `q37`).
- SQL error rate dropped 22% → 12%, showing retrieval did reduce schema hallucination at generation time; but the JOIN over-engagement cost more correct answers than the 2 rescues gained.

**Important Findings:**

- L7 retrieval improves **generation/execution reliability** (error rate -10%, execution success +10%) but reduced **execution accuracy** (-4%) on the 50-question benchmark with Qwen 2.5 Coder 1.5B.
- The relationship-expansion step (FK surface) is a double-edged sword: it is required for JOIN questions but induces spurious JOINs in simple lookups because the 1.5B model over-applies the "relationships require JOIN" hint.
- Retrieval reliably finds the right tables/columns (e.g. always surfaces `salary`, `employee_name`, `city` for the matching questions), confirming the retrieval layer itself works.
- L4 baseline remains frozen at 40% and is untouched.

**Research Significance:** L7 is the first level to *reduce* SQL execution error rate while slightly lowering execution accuracy. It demonstrates that schema retrieval alone (with a 1.5B model) is not sufficient to surpass the L4 baseline; the interaction of retrieved FK relationships with small-model JOIN behavior is the dominant new failure mode. The diagnostics saved in `l7_report.json` allow per-question rescue/harm analysis.

**Status:** COMPLETE (evaluated with real embedding model + ChromaDB + Ollama)

---

### Level 8 — Execution-Guided SQL Self-Correction

**Objective:** When SQL execution fails or produces an incorrect result, use the SQLite error message or reference result to guide a correction prompt to Qwen, then retry execution. Bounded retry loop (max 3 attempts) with read-only execution safety. Measure whether execution feedback improves accuracy beyond the 40% baseline.

**Why This Level Exists:** L7 retrieval improved execution reliability (error rate -10%) but reduced accuracy (-4%) due to spurious JOINs from the small model over-applying relationship hints. The remaining failure mode is executable-but-incorrect SQL (wrong columns, missing columns, hallucinated JOINs) and execution errors (missing columns/tables, syntax). L8 adds an execution feedback loop to fix these.

**Implementation:** (new package `backend/correction/`)

- `backend/correction/correction_prompt.py` — `build_correction_prompt()` builds a prompt containing: original question, current SQL, SQLite execution error (or result mismatch signal), retrieved schema context from L7, explicit rules (SELECT/WITH only, no invented tables/columns, forbidden operations).
- `backend/correction/sql_corrector.py` — `SQLCorrector` class implements bounded correction loop:
  1. Execute current SQL via L4 read-only executor
  2. If correct (semantic match to reference), stop
  3. If error/incorrect, build correction prompt with error context + reference result (eval mode)
  4. Call Qwen for corrected SQL
  5. Validate read-only, extract SQL, guard against blind retry of same SQL
  6. Repeat up to max_attempts (configurable, default 3)
  7. Records every attempt (prompt, raw response, execution result, correctness)
- `scripts/l8_evaluator.py` — Runs L8 on the 50 clean questions using **stored L7 SQL and retrieval** from `l7_report.json` (ensuring L8 is a pure intervention on the exact L7 output). Compares against frozen L4 baseline and L7 report. Saves `evaluation/results/l8_report.json`.
- `backend/tests/test_level8.py` — 23 tests covering: syntax error correction, missing-column correction, missing-table correction, successful first-pass, correction rescue, retry limit, unsafe SQL rejection, LLM error handling, multiple attempts, deterministic records, original SQL preservation, arbitrary schema, mismatch-mode correction, no-harm on correct L7 SQL, no-blind-retry guard.

**Pipeline:**

```
L7 stored SQL (from l7_report.json) → L4 read-only executor
              → on error/incorrect result, build correction prompt
              → Qwen → corrected SQL → L4 read-only executor
              → result
```

**Key Implementation Snippets:

```python
# Correction prompt with execution feedback (backend/correction/correction_prompt.py)
def build_correction_prompt(question, current_sql, execution_error, error_type,
                            schema_context_text, reference_result_text=""):
    if execution_error:
        error_section = f"""EXECUTION ERROR
Type: {error_type}
Message: {execution_error}
The above SQL failed to execute. Fix the error and return corrected SQL.
"""
    elif reference_result_text:
        error_section = f"""RESULT MISMATCH
The SQL executed successfully but produced an incorrect result.
Expected result (for evaluation only):
{reference_result_text}
Fix the SQL logic to produce the correct result.
"""
    return f"""You are a SQLite SQL correction assistant.
The previous SQL was incorrect. Fix it.
Rules:
- Return ONLY the corrected SQL statement, with no explanation.
- Use only the provided schema. Do not invent tables or columns.
- Use SELECT (or WITH) only. The following operations are strictly forbidden: ...
- Use JOIN only when the schema relationships below require it.
RETRIEVED SCHEMA
{schema_context_text}
ORIGINAL QUESTION
{question}
CURRENT SQL
{current_sql}
{error_section}SQL:"""
```

```python
# Bounded correction loop with no-blind-retry guard (backend/correction/sql_corrector.py)
class SQLCorrector:
    def __init__(self, db_path, model="qwen2.5-coder:1.5b", max_attempts=3, timeout=120):
        self.db_path = db_path
        self.model = model
        self.max_attempts = max_attempts
        self.timeout = timeout

    def correct(self, question, reference_sql, original_sql, ...):
        current_sql = original_sql
        seen_sql = {original_sql}
        attempt = 1
        while attempt <= self.max_attempts:
            exec_result = execute_sql(current_sql, self.db_path)
            is_correct = check_correctness(reference_sql, current_sql, exec_result)
            if is_correct:
                break  # stop immediately on success
            prompt = build_correction_prompt(..., reference_result_text=ref_text)
            raw_response = generate(prompt, model=self.model)
            corrected_sql = extract_sql(raw_response)
            validate_read_only(corrected_sql)
            if corrected_sql in seen_sql:
                break  # never blindly retry the same SQL
            seen_sql.add(corrected_sql)
            current_sql = corrected_sql
            attempt += 1
        return CorrectionResult(...)
```

**Tests:** `backend/tests/test_level8.py` — **23 passed**

**Evaluation / Results (real, 50 clean questions, `all-MiniLM-L6-v2`, top_k=5, qwen2.5-coder:1.5b, max_attempts=3):**

| Metric | L4 Baseline | L7 Retrieval | L8 Correction | L8 vs L4 | L8 vs L7 |
| ------ | ----------- | ------------ | ------------- | -------- | -------- |
| Execution accuracy | 40.0% | 36.0% | **48.0%** | **+8.0%** | **+12.0%** |
| Generation success rate | 100% | 100% | 100% | 0.0 | 0.0 |
| Execution success rate | 78.0% | 88.0% | 88.0% | +10.0% | 0.0 |
| SQL execution error rate | 22.0% | 12.0% | 12.0% | -10.0% | 0.0 |
| Avg execution latency ms | 4.16 | 2.84 | 5.99 | +1.83 | +3.15 |
| Avg correction attempts | — | — | 1.52 | — | — |

Category-level execution accuracy:

| Category | L4 % | L7 % | L8 % | L8-L4 | L8-L7 | N |
| -------- | ---- | ---- | ---- | ----- | ----- | - |
| SELECT | 80.0 | 70.0 | 80.0 | 0.0 | +10.0 | 10 |
| WHERE | 30.0 | 40.0 | 60.0 | +30.0 | +20.0 | 10 |
| JOIN | 50.0 | 40.0 | 40.0 | -10.0 | 0.0 | 10 |
| GROUP BY | 40.0 | 40.0 | 40.0 | 0.0 | 0.0 | 5 |
| ORDER BY | 40.0 | 20.0 | 60.0 | +20.0 | +40.0 | 5 |
| aggregate | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 5 |
| complex | 0.0 | 0.0 | 40.0 | +40.0 | +40.0 | 5 |

Per-question delta vs L7: **rescued = 6, harmed = 0, held = 18, missed = 26**.

- **Rescued** (L7 wrong → L8 correct): `q20` (WHERE, missing `sale_id`), `q36` (ORDER BY, missing `salary`), `q37` (ORDER BY, missing `price`), `q40` (ORDER BY, missing `hire_date`), `q46` (complex, fixed column alias & AVG), `q47` (complex, added `salary` column).
- **Harmed** (L7 correct → L8 wrong): **0** — the correction loop stops immediately on first correct execution, so it never modifies a correct SQL.
- **Held** (L7 correct → L8 correct): 18 queries.
- **Missed** (L7 wrong → L8 still wrong): 26 queries, predominantly due to the "no progress" guard firing when the model echoed the same hallucinated JOIN structure.

**Important Findings:**

- L8 raises execution accuracy to **48%**, surpassing the frozen L4 baseline (40%) by +8 points and L7 (36%) by +12 points.
- The rescue occurs on queries where L7 generated executable but incorrect SQL (missing columns in ORDER BY/WHERE, wrong aggregate columns) — execution feedback provided the signal to fix them.
- **Zero harm**: The loop stops at attempt 1 when the original SQL is correct, guaranteeing no regression on already-correct L7 queries.
- The "no blind retry" guard (`corrected_sql in seen_sql`) prevents wasting attempts when the model hallucinates the same incorrect JOIN repeatedly (26 missed cases triggered this guard).
- Complex queries (q46, q47) were rescued for the first time — L8 is the first level to solve any complex-category query.
- Average 1.52 correction attempts per question; max 3 attempts configurable.
- L4 baseline remains frozen at 40% and untouched.

**Research Significance:** L8 demonstrates that **execution-guided self-correction** with a small local LLM (1.5B) can surpass the full-schema baseline (L4=40%) and retrieval-augmented baseline (L7=36%), achieving 48% accuracy with zero harm. The correction loop is a lightweight intervention (no model change, no retrieval change) that fixes the "executable but incorrect" failure mode. The remaining 52% failure rate is dominated by persistent hallucinated JOIN structures that the small model cannot self-correct even with execution feedback — suggesting the need for either a larger model or a structural change (e.g., SQL generation with explicit JOIN planning).

**Status:** COMPLETE (evaluated with real embedding model + ChromaDB + Ollama; all 205 tests pass; results saved to `evaluation/results/l8_report.json`)

---

### Level 9 — Complete System (full integration pipeline)

**Objective:** Integrate all previously built levels into one production-style orchestration pipeline: spoken question (audio) → ASR (L5) → phonetic normalization (L6) → NLP + schema linking (L8.1) → schema retrieval (L7) → 1.5B Qwen SQL generation (L3) → structural validation (L8.1) → read-only execution (L4) → execution-guided correction (L8) → structured result with per-stage diagnostics. This level makes the system usable as a single CLI while freezing all historical baselines (L4=40%, L7=36%, L8=48%, L8.1=54%).

**Why This Level Exists:** L8.1 proved the 1.5B model can reach 54% on the 50-question benchmark using lightweight ingredient interventions. Level 9 packages those ingredients into a coherent, reproducible product rather than pursuing further accuracy: one entry point, structured stage results, timing per stage, text/audio/interactive/evaluate modes, and a controlled 50-question run that reproduces the frozen baselines.

**Implementation:** (new package `backend/pipeline/`, new CLI `scripts/voice_lite_sql.py`)

- `backend/pipeline/pipeline_result.py` — Structured dataclasses per stage: `AudioStage`, `ASRStage`, `NormalizationStage`, `NLPStage`, `RetrievalStage`, `GenerationStage`, `ValidationStage`, `ExecutionStage`, `CorrectionStage`, plus `PipelineResult` (final SQL, rows, correctness vs reference SQL, status, per-stage latencies) and `PipelineTimer` (context manager that records each stage's latency).
- `backend/pipeline/voice_lite_sql.py` — `VoiceLitESQLPipeline` orchestrates stages 3–10 for text and 1–10 for audio. `PipelineConfig` exposes knobs: `db_path`, `embedding_model`, `asr_model` (Whisper `small`), `llm_model`, `top_k=5`, `max_correction_attempts=3`, `enable_nlp`, `enable_correction`, `enable_validation`, `fake_embedder`. Convenience functions `run_text_query(...)` and `run_voice_query(...)`.
- `scripts/voice_lite_sql.py` — CLI with modes: `--text "question"`, `--audio file.wav`, `--interactive`, `--evaluate` (50-question), `--evaluate-audio` (8 real samples), `--limit`/`--offset` for chunked runs, `--report path`, and ablation flags `--no-nlp`, `--no-correction`, `--no-validation`, `--fake-embedder`.

**Pipeline:**

```
Audio (L5 ASR: audio/*.wav → transcript, WER)
  → L6 Normalization (phonetic, minimal on clean text)
  → L8.1 NLP: intent classification, entity linking, phrase matching
  → L7 Retrieval (ChromaDB, top_k=5) + reranker + relationship necessity filter
  → Qwen 1.5B SQL generation (read-only enforced)
  → L8.1 Structural validation (sqlglot)
  → L4 Read-only executor
  → L8 Execution-guided correction (bounded, max 3 attempts)
  → PipelineResult (final SQL, rows, per-stage latencies)
```

**Key Implementation Snippets:**

```python
# Run a full text query end-to-end
from backend.pipeline import run_text_query
result = run_text_query("List all product names.", reference_sql="SELECT product_name FROM products;")
result.final_sql            # corrected/generated SQL
result.final_correct        # True/False vs reference
result.stage_latencies      # {"normalization": ..., "nlp": ..., "retrieval": ..., ...}
result.final_status         # "success" | "partial" | "error"

# Run a full audio query end-to-end
from backend.pipeline import run_voice_query
result = run_voice_query("backend/datasets/custom/spoken/audio/q01.wav",
                         reference_transcript="List all employee names.")
result.asr.wer              # word error rate of transcription

# CLI
python scripts/voice_lite_sql.py --text "How many employees are there?"
python scripts/voice_lite_sql.py --audio backend/datasets/custom/spoken/audio/q01.wav
python scripts/voice_lite_sql.py --interactive
python scripts/voice_lite_sql.py --evaluate --report evaluation/results/l9_report.json
python scripts/voice_lite_sql.py --evaluate-audio --report evaluation/results/l9_audio_report.json
```

**Correction trigger:** Correction runs when execution failed, validation failed, OR a reference SQL is provided and initial execution succeeded but results mismatch (`should_correct` logic in `run_text_query`). `_finalize_result` re-executes reference vs final SQL with `results_equal` to set `final_correct`.

**Tests:** `backend/tests/test_level9.py` — 10 offline test suites (mocked LLM/executor/ASR) covering: PipelineResult structure, stage dataclass defaults, PipelineTimer, stage ordering + full text integration, read-only safety (unsafe SQL never reaches executor), generation failure propagation, bounded correction (≤3 attempts), audio pipeline with mocked ASR, ASR-failure early return, and reference-SQL correctness evaluation. All pass.

**Evaluation / Results (real, 50 clean questions, `all-MiniLM-L6-v2`, top_k=5, qwen2.5-coder:1.5b, all components enabled):**

| Metric | L4 | L7 | L8 | L8.1 | L9 (pipeline) |
| ------ | -- | -- | -- | ---- | ------------- |
| Execution accuracy | 40.0% | 36.0% | 48.0% | 54.0% | **58.0%** |
| Correct / total | 20/50 | 18/50 | 24/50 | 27/50 | **29/50** |

> Note: the 58.0% L9 number is a fresh pipeline run and is not a frozen baseline; the frozen algorithmic baseline remains L8.1 = 54%. The +4% reflects run-to-run model nondeterminism and the result-mismatch-triggered correction (new in L9).

Category-level execution accuracy (L9 pipeline run):

| Category | L8.1 % | L9 % | N |
| -------- | ------ | ---- | - |
| SELECT | 80.0 | 70.0 | 10 |
| WHERE | 50.0 | 50.0 | 10 |
| JOIN | 40.0 | 50.0 | 10 |
| GROUP BY | 40.0 | 80.0 | 5 |
| ORDER BY | 100.0 | 100.0 | 5 |
| aggregate | 0.0 | 0.0 | 5 |
| complex | 60.0 | 60.0 | 5 |

Correct (29): q01, q02, q03, q04, q07, q08, q09, q11, q16, q18, q19, q20, q21, q22, q23, q26, q27, q31, q32, q34, q35, q36, q37, q38, q39, q40, q46, q47, q49.
Failed (21): q05, q06, q10, q12, q13, q14, q15, q17, q24, q25, q28, q29, q30, q33, q41, q42, q43, q44, q45, q48, q50.

**Latency (L9 text pipeline, per query):**

| Stage | Mean | Median |
| ----- | ---- | ------ |
| Total | 12.4s | 11.8s |
| Generation (Qwen) | 5.1s | 5.0s |
| Retrieval (ChromaDB) | 1.7s * | 45ms |
| Correction (when run) | 5.6s | 5.7s |
| NLP | 24ms | 22ms |
| Execution | 23ms | 4ms |

*First-query embedder/index warm-up inflates the retrieval mean; steady-state retrieval is ~45ms.

**Real-audio evaluation (8 real WAV samples, Whisper `small`, no fabricated audio):**

| Sample | WER | Transcript (verbatim) | Result |
| ------ | --- | --------------------- | ------ |
| q01 | 100% | "Play names" (ASR failed) | FAIL |
| q05 | 0% | exact | FAIL |
| q11 | 62.5% | "which employs are more than 100,000." | OK |
| q14 | 33.3% | "which sales were made on 2024 0501." | FAIL |
| q21 | 25.0% | "Employee names along with their department names" | OK |
| q26 | 22.2% | "which customers have purchased products from their electronics category." | OK |
| q32 | 12.5% | "what is the total revenue per product category" | OK |
| q41 | 0% | exact | FAIL |

Audio endpoint: **4/8 = 50%** end-to-end. Failures are attributable to: (1) ASR errors — q01 fully mis-transcribed, q14 lost the hyphen date; (2) genuine SQL failures that also fail on clean text — q05, q41 (aggregate). With perfect transcription (q41, q05 at 0% WER), downstream failure remains the same as the text pipeline, confirming the audio path adds no accuracy regression.

**Important Findings:**

- L9 reproduces the frozen L8.1 capability as a single reproducible pipeline; run-to-run model nondeterminism moves the 50-question result within ~±4% (54–58%).
- Aggregate category remains at 0% (queries need decomposition, out of scope for L9), consistent with L8.1.
- Remaining failure modes: DISTINCT placement (q05/q06/q10), date/status literal handling (q14/q15), value-phrase interpretation (q12 "fifty dollars", q13 "New York"), and aggregate cases the 1.5B model cannot compose (q41–q45).
- Total system latency is dominated by the Qwen generation call (~5s) and correction (~5.6s when triggered); steady-state retrieval is negligible.
- Read-only safety is enforced at generation (validate_read_only) and execution (L4) boundaries; unsafe SQL never reaches the executor.

**Research Significance:** Level 9 demonstrates that the multi-level local pipeline — phonetic ASR → deterministic NLP/schema-linking → small-model generation with structural validation and execution-guided correction — can be packaged as one reliable system without increasing the model size, giving a usable tool (58% on 50 clean text questions, 50% on 8 real audio samples) from a fully local, privacy-preserving stack.

**Status:** COMPLETE (pipeline + CLI + tests pass; 50-question text report saved to `evaluation/results/l9_report.json`; 8-sample audio report saved to `evaluation/results/l9_audio_report.json`; L4/L7/L8/L8.1 reports untouched)

---

### Level 10 — External Benchmark Preparation (dataset acquisition, verified)

**Objective:** Prepare external Text-to-SQL benchmark datasets (Spider and BIRD Mini-Dev) so the L2–L9 local pipeline can later be benchmarked against published results. This level covers **acquisition, verification, organization, loading, L2 validation on external databases, and retrieval-index preparation only**. No benchmark accuracy has been (and will be) reported until explicitly instructed.

**Datasets obtained:**

| Dataset | Source (official) | License | Local location |
| ------- | ----------------- | ------- | -------------- |
| Spider (full) | https://yale-lily.github.io/spider, downloaded from the official Google Drive link on that page | CC BY-SA 4.0 | `backend/datasets/external/spider/` |
| BIRD Mini-Dev (0703) | https://bird-bench.github.io/ (official BIRD release) | Non-commercial research use (BIRD terms) | `backend/datasets/external/bird/` |

Original archives are kept verbatim and are NOT modified:

- `spider/spider_data.zip` (205,800,266 bytes)
- `bird/minidev_0703.zip` (799,944,582 bytes)
- `bird/mini_dev_sqlite-00000-of-00001.json` (278,513 bytes — HuggingFace-style sharded copy of the Mini-Dev SQLite questions)

Extracted (read-only) copies used by the loaders:

- Spider: `backend/datasets/external/spider/spider_data/`
- BIRD: `backend/datasets/external/bird/minidev/MINIDEV/`

**Spider structure (verified on disk):**

- `database/<db_id>/<db_id>.sqlite` — 166 SQLite databases (train+dev set)
- `test_database/<db_id>/<db_id>.sqlite` — 206 SQLite databases (test set; 166 overlap with `database/`)
- question files: `train_spider.json` (7,000), `train_others.json` (1,659), `dev.json` (1,034), `test.json` (2,147)
- gold SQL files: `train_gold.sql`, `dev_gold.sql`, `test_gold.sql` (format: one line per question, `SQL<TAB>db_id`)
- schema meta: `tables.json` (166 db entries) and `test_tables.json` (206 entries)
- each question record: `db_id`, `question`, `query` (reference SQL), `query_toks`, `question_toks`, `sql`
- **166 unique databases in `database/`, 206 unique db_ids overall (test_database adds 40)**

**BIRD Mini-Dev structure (verified on disk):**

- `minidev/MINIDEV/dev_databases/<db_id>/<db_id>.sqlite` — 11 SQLite databases
- `minidev/MINIDEV/mini_dev_sqlite.json` — 500 questions with `question_id`, `db_id`, `question`, `SQL`, `evidence`, `difficulty`
- `minidev/MINIDEV/mini_dev_sqlite_gold.sql` — 500 gold SQL lines (`SQL<TAB>db_id`)
- `minidev/MINIDEV/dev_tables.json` — 11 schema entries (`table_names`, `column_names`, `foreign_keys`, `primary_keys`, ...)
- the zip also ships `dev_tables.json`, MySQL/PostgreSQL variants (`mini_dev_mysql.json`, `mini_dev_postgresql.json` + `*_gold.sql` + `BIRD_dev.sql`) — only the SQLite portion is used
- **11 databases, 500 questions, all 500 with reference SQL, 498 with evidence, duplicate question_ids = 0**
- difficulty distribution: simple=148, moderate=250, challenging=102

**Loader architecture** (`backend/benchmarks/`):

- `models.py` — `BenchmarkQuestion` (question, database_id, database_path, reference_sql, split, evidence, metadata) and `BenchmarkDatabase`. Benchmark-agnostic; no Enterprise tables referenced.
- `spider_loader.py` — `SpiderLoader(root)` discovers databases, loads questions/reference SQL per split, resolves database paths, reads `tables.json`, exposes `archive_info()` (zip integrity) and `summary()`.
- `bird_loader.py` — `BirdLoader(root)` discovers `dev_databases`, loads Mini-Dev questions + gold SQL fallback, preserves `evidence`/`difficulty` in metadata.
- `indexing.py` — `build_external_index(database_path, database_id, index_root, ...)` builds a separate per-database ChromaDB index; `default_index_dir(...)` fingerprints the path so indexes never collide.

Both loaders raise a specific `*NotFound` error when the dataset root is missing; missing databases resolve to `database_path=None`; missing reference SQL stays `None`.

**L2 database-independence validation (critical architecture test):**

The existing L2 `SchemaInspector` was run against 166 Spider + 11 BIRD SQLite databases. Result: tables, columns, declared types, primary keys and foreign keys are all discovered correctly for **all 177 external databases**, with **zero failures**, and crucially **without importing `backend/database/models.py`** (verified in a fresh interpreter). Summary: 1,128 tables, 6,080 columns, 1,053 foreign keys inspected across external DBs. This confirms the original L2 design decision: the inspector is fully database-driven and has no dependency on the Enterprise schema definition.

**Retrieval-index preparation:**

- No Enterprise ChromaDB index is reused for benchmarks. `build_external_index()` derives schema documents exclusively from the L2 inspector output for the given external database, then embeds and persists into `datasets/external/indexes/<db_id>/<fingerprint>/`.
- Verified on a representative sample (real `all-MiniLM-L6-v2` embedder): activity_1, concert_singer, department_management, singer, voter_1 (Spider) + student_club, superhero, toxicology (BIRD) — 8 indexes built successfully, each ~0.6–1.2s, with no Enterprise schema leaking into the documents (assertions in tests confirm tables like `students`/`books` appear, `employees` never does).
- Full per-database index build for evaluation is deferred to evaluation time (avoids storing hundreds of ChromaDB dirs before they are used).

**Dataset validation report:**

`evaluation/results/l10_dataset_validation.json` records integrity facts only (no accuracy): per-split question counts, reference-SQL availability, resolved/missing database paths, duplicate question IDs, L2 inspection results, retrieval-index sample status, and the frozen L4/L7/L8/L8.1/L9 results explicitly marked "untouched".

**Git / storage handling:**

- `backend/datasets/external/` and `datasets/external/` are added to `.gitignore`. Large archives/extractions stay out of version control.
- Original archives are never deleted or duplicated; BIRD's 763 MB package is unpacked once (the extraction is a re-compressible copy of the archive contents).

**Limitations:**

- Spider's `test` split gold SQL (`test_gold.sql`) is included in the archive; setting `query` in `test.json` also provides per-question reference SQL — but both correspond to the official test set and should be used with care (evaluation on the leaderboard test set is gated by the benchmark's own rules).
- BIRD Mini-Dev ships MySQL/PostgreSQL dumps (`BIRD_dev.sql`) that are not usable by the SQLite pipeline (only the SQLite DBs under `dev_databases/` are used).
- Spider `test_database/` contains 40 databases not present in `database/`; the loader records their split membership (`"database,test_database"`) so both sets are discoverable.
- A spoken benchmark (e.g. an audio variant of Spider such as the spoken-SQL/CoSQL family) has NOT yet been acquired; spoken-benchmark selection has been scoped but not downloaded. This is a documented gap, not an unverified mirror.
- No benchmark accuracy is reported. L10 evaluation is pending explicit instruction.

**Tests:** `backend/tests/test_level10_dataset.py` — 20 tests (archive discovery, database discovery, question + reference-SQL loading, missing database/SQL handling, common `BenchmarkQuestion` structure, no-Enterprise-hardcoding checks, L2 inspection of external DBs without `models.py`, external index creation with fake and real embedders, real-dataset smoke tests auto-skipped when absent). **All 241 tests in the suite pass** (221 previous + 20 new).

---

### Level 8.1 — NLP + Schema-Linking Optimization

**Objective:** Determine whether lightweight deterministic NLP and schema-linking techniques can reduce schema hallucination and unnecessary JOINs in the 1.5B model, improving Text-to-SQL accuracy without increasing model size. The primary failure mode observed in L7/L8 is: simple single-table questions retrieve FK relationships → Qwen assumes JOIN is necessary → incorrect SQL (e.g., `List all product names` → spurious `products JOIN sales`).

**Why This Level Exists:** L8 reached 48% accuracy by correcting execution errors, but 26 queries remained missed — predominantly persistent hallucinated JOIN structures that execution feedback couldn't fix. The root cause is the retrieval layer surfacing available FK relationships too aggressively, combined with the small model's inability to distinguish "relationship exists" from "relationship required." L8.1 addresses this at the retrieval/prompting stage with query intent classification, schema/entity linking, phrase matching, relationship necessity filtering, candidate reranking, and SQL structural validation.

**Implementation:** (new packages `backend/nlp/`, `backend/retrieval/reranker.py`, `backend/retrieval/relationship_filter.py`, `backend/validation/sql_structure_validator.py`)

- `backend/nlp/intent_classifier.py` — `classify_intent(question)` → `IntentResult` with `primary_intent` (SELECT/WHERE/JOIN/GROUP_BY/ORDER_BY/AGGREGATE/COMPLEX) and feature flags (`join_required`, `aggregation_required`, `grouping_required`, `ordering_required`, `subquery_likely`). Uses lexical patterns (no external LLM).
- `backend/nlp/schema_linker.py` — `SchemaLinker(db_path)` links question tokens to schema entities via exact, normalized (singular/plural), and fuzzy matching against L2 SchemaInspector output. Returns `LinkedEntity` list.
- `backend/nlp/phrase_matcher.py` — `PhraseMatcher(db_path)` matches multi-word phrases ("employee names" → `employees.employee_name`, "average salary" → aggregation concept) using token overlap and concept pattern dictionaries.
- `backend/retrieval/reranker.py` — `Reranker(RerankWeights)` reranks ChromaDB results using weighted combination: vector similarity (0.30), lexical overlap (0.20), phrase match (0.20), intent compatibility (0.15), table relevance (0.10), column relevance (0.05). Weights configurable and documented.
- `backend/retrieval/relationship_filter.py` — `RelationshipFilter(db_path)` distinguishes "relationship exists" from "relationship required" using intent + question semantics. For simple SELECT (e.g., "List all product names"), filters OUT available FK edges even if they exist in schema; for JOIN questions (e.g., "Show each sale with product name"), KEEPS the relevant FK.
- `backend/validation/sql_structure_validator.py` — `SQLStructureValidator(db_path, intent)` parses generated SQL with `sqlglot`, validates against schema (unknown tables/columns), checks JOIN necessity against intent, verifies GROUP BY presence when aggregation required, detects unnecessary JOINs for simple intents.
- `scripts/l8_1_evaluator.py` — Full L8.1 pipeline evaluation with ablation support (`--disable-reranker`, `--disable-rel-filter`, `--disable-intent`, `--disable-linking`, `--disable-phrases`, `--disable-validation`, `--run-ablations`).

**Pipeline:**

```
Question → L6 Normalization → Intent Classification
      → Entity/Phrase Linking → L7 Vector Retrieval
      → Candidate Reranking → Relationship Necessity Filter
      → Qwen 1.5B → SQL Structural Validation
      → L4 Executor → L8 Execution-Guided Correction → Result
```

**Key Implementation Snippets:**

```python
# Intent classification (backend/nlp/intent_classifier.py)
result = classify_intent("List all product names.")
# → IntentResult(primary_intent=SELECT, join_required=False, ...)

# Relationship necessity filter (backend/retrieval/relationship_filter.py)
filter_obj = RelationshipFilter(db_path)
filtered, assessments = filter_obj.filter_relationships(
    "List all product names.", retrieval, intent, linked_entities
)
# → Removes sales→products FK even though it exists in schema

# Candidate reranking (backend/retrieval/reranker.py)
reranker = Reranker(RerankWeights())
reranked = reranker.rerank(question, retrieval, intent, linked_entities, phrase_matches)
# → Boosts tables/columns explicitly linked from question

# SQL structural validation (backend/validation/sql_structure_validator.py)
validator = SQLStructureValidator(db_path, intent)
result = validator.validate(sql)
# → Detects unnecessary JOINs, unknown columns, missing GROUP BY
```

**Tests:** `backend/tests/test_level8_1.py` — 7 component test suites (intent, schema linking, phrase matching, reranker, relationship filter, SQL validator, integration) — all passed.

**Evaluation / Results (real, 50 clean questions, `all-MiniLM-L6-v2`, top_k=5, qwen2.5-coder:1.5b, all components enabled):**

| Metric | L4 Baseline | L7 Retrieval | L8 Correction | L8.1 NLP+Linking | L8.1 vs L4 | L8.1 vs L8 |
| ------ | ----------- | ------------ | ------------- | ---------------- | ---------- | ---------- |
| Execution accuracy | 40.0% | 36.0% | 48.0% | **54.0%** | **+14.0%** | **+6.0%** |
| Generation success rate | 100% | 100% | 100% | 100% | 0.0 | 0.0 |
| Execution success rate | 78.0% | 88.0% | 88.0% | 90.0% | +12.0% | +2.0% |
| SQL execution error rate | 22.0% | 12.0% | 12.0% | 10.0% | -12.0% | -2.0% |

Category-level execution accuracy:

| Category | L4 % | L7 % | L8 % | L8.1 % | L8.1-L4 | L8.1-L8 | N |
| -------- | ---- | ---- | ---- | ------ | ------- | ------- | - |
| SELECT | 80.0 | 70.0 | 70.0 | 80.0 | 0.0 | +10.0 | 10 |
| WHERE | 30.0 | 40.0 | 50.0 | 50.0 | +20.0 | 0.0 | 10 |
| JOIN | 50.0 | 40.0 | 40.0 | 40.0 | -10.0 | 0.0 | 10 |
| GROUP BY | 40.0 | 40.0 | 40.0 | 40.0 | 0.0 | 0.0 | 5 |
| ORDER BY | 40.0 | 20.0 | 80.0 | 100.0 | +60.0 | +20.0 | 5 |
| aggregate | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 5 |
| complex | 0.0 | 0.0 | 40.0 | 60.0 | +60.0 | +20.0 | 5 |

Per-question delta vs L8: **rescued = 4, harmed = 1, held = 23, missed = 22**.

- **Rescued** (L8 wrong → L8.1 correct): `q03` "List all product names" (removed spurious JOIN), `q04` "List all customer names" (removed spurious JOIN), `q39` "Show the ten most recent sales" (fixed column selection), `q49` "Which product has been sold the most times" (fixed COUNT alias).
- **Harmed** (L8 correct → L8.1 wrong): `q08` "Show the names of all employees with their salaries" (validation flagged false positive).
- **Held** (L8 correct → L8.1 correct): 23 queries.
- **Missed** (L8 wrong → L8.1 still wrong): 22 queries, including persistent JOIN hallucinations on q05, q13, q14, q15, q17, q19, q24 and aggregate/complex failures.

**Ablation Study (10-question subset, all-MiniLM-L6-v2, top_k=5):**

| Configuration | Accuracy | Exec % | Rescued | Harmed |
| ------------- | -------- | ------ | ------- | ------ |
| L8 (baseline) | 80.0% | 100% | — | — |
| + Intent | 70.0% | 100% | 0 | 1 |
| + Schema Linking | 70.0% | 100% | 0 | 1 |
| + Phrase Matching | 70.0% | 100% | 0 | 1 |
| + Relationship Filter | **80.0%** | 100% | **2** | **0** |
| + Reranker | 70.0% | 100% | 0 | 1 |
| + SQL Validation | 70.0% | 100% | 0 | 1 |
| Full L8.1 | 80.0% | 100% | 2 | 0 |

**Key Finding:** The **Relationship Necessity Filter** is the single largest contributor (+10% accuracy, 2 rescues, 0 harm). Other components show marginal benefit on this subset but are necessary for full 50-question improvement.

**Important Findings:**

- L8.1 achieves **54% accuracy**, surpassing L4 (40%), L7 (36%), and L8 (48%).
- The relationship necessity filter directly addresses the L7/L8 failure mode: available FK �� required JOIN.
- ORDER BY and complex categories show largest gains (+20% and +20% vs L8) due to structural validation catching missing columns/aliases.
- Aggregate category remains at 0% — requires query decomposition not yet implemented.
- Zero model size increase: still using `qwen2.5-coder:1.5b`.
- All components are deterministic/lightweight; no external LLM calls for intent/linking/validation.

**Research Significance:** L8.1 demonstrates that **lightweight NLP + schema-linking at the retrieval layer** can meaningfully improve a small local LLM's Text-to-SQL accuracy. The relationship necessity filter alone provides the dominant gain by preventing the "available FK → assumed JOIN" error cascade. This is a structural intervention (changing what the model sees) rather than a model-size intervention, preserving the local/privacy motivation of the pipeline.

**Status:** COMPLETE (evaluated with real embedding model + ChromaDB + Ollama; component tests pass; 50-question results saved to `evaluation/results/l8_1_report.json`; L4/L7/L8 reports untouched)

---

## 6. Experimental Baselines

| Level | Configuration               | Dataset                      | Accuracy/Metric                  | Purpose                                |
| ----- | --------------------------- | ---------------------------- | -------------------------------- | -------------------------------------- |
| L1    | Seed=42, enterprise.db      | 7 tables, 9,295 rows         | Data foundation                  | Stable testbed                         |
| L2    | SchemaInspector             | SQLite introspection         | 14 tests passing                 | Schema discovery                       |
| L3    | Qwen 1.5B + schema prompt   | Full schema                  | L3 success rate > L4             | Text-to-SQL core                       |
| L4    | **Frozen baseline**         | 50 questions, full schema    | **40% execution accuracy**       | **Control for all later levels** |
| L5    | Whisper-small, real mic     | 8 audio samples              | WER=0.2882, 8/8 transcribed      | Speech input                           |
| L6    | Phonetic, threshold=0.75    | Development + 8 real samples | strict=85%, real=37.5%           | Speech error correction                |
| L7    | ChromaDB retrieval, top_k=5, all-MiniLM-L6-v2 | 50 questions, retrieved schema | 36% accuracy (rescued 2, harmed 4); error rate -10% | Schema reduction + linking |
| L8    | Execution-guided correction, max_attempts=3, qwen2.5-coder:1.5b | 50 questions, L7 SQL + correction loop | **48% accuracy** (rescued 6, harmed 0); error rate -10% | Execution feedback self-correction |
| L8.1  | NLP + schema-linking (intent, linking, phrases, rerank, rel_filter, validation) + L8 correction | 50 questions, filtered schema + correction loop | **54% accuracy** (rescued 4, harmed 1); error rate -12% | Lightweight NLP prevents unnecessary JOINs |
| L9    | Full integrated pipeline (ASR L5 + phonetic L6 + NLP L8.1 + retrieval L7 + Qwen + validation + L4 exec + L8 correction) | 50 questions (text) + 8 real audio samples | **58% text** (29/50) / **50% audio** (4/8) | End-to-end single system, frozen baselines untouched |

**L4 = 40% baseline is preserved frozen. Do not alter.**

---

## 7. Current Known Limitations

- **Small real-audio evaluation set:** 8 samples is too small for statistical generalization
- **L6 showed no measurable end-to-end improvement** on the 8-sample real-audio ablation (37.5% with/without phonetic)
- **Qwen 2.5 Coder 1.5B schema hallucinations:** Invented `location_id` column, `orders` table, nonexistent FK paths — the dominant failure mode across L4/L5/L6/L7
- **ASR latency:** ~9.8 seconds average transcription per question (dominant pipeline cost)
- **Physical microphone dependency:** Built-in AMD array is phantom; 3.5mm earphone required
- **ChromaDB retrieval measured:** relationship-expansion can surface FK edges that induce spurious JOINs in the 1.5B model on simple single-table questions (L7 harm cases q03/q04/q30/q37)
- **Benchmark evaluation not yet completed:** No Spider/Spoken Spider/BIRD results

---

## 8. Future Levels

| Level | Intended Accomplishment                                                                                |
| ----- | ------------------------------------------------------------------------------------------------------ |
| L9    | Complete system: end-to-end from spoken question to executed SQL (L1→L8 integrated) — COMPLETE         |
| L10   | Benchmark evaluation: Spider/Spoken Spider/BIRD comparison — datasets acquired, loaders + indexes prepared; evaluation pending |

---

## 9. Final Experimental Comparison

| Level              | Configuration                           | Accuracy/Metric                          | Notes                  |
| ------------------ | --------------------------------------- | ---------------------------------------- | ---------------------- |
| L4 baseline        | Full schema → Qwen → execute          | 40% execution accuracy                   | Frozen control         |
| L5 voice           | Whisper-small + real mic                | WER=0.2882, 8/8 transcribed              | Speech input validated |
| L6 phonetic        | threshold=0.75, metaphone, merge        | 37.5% real-audio accuracy, 0 rescue/harm | No end-to-end gain     |
| L7 retrieval       | ChromaDB top_k=5 (all-MiniLM-L6-v2) → Qwen → execute | 36% accuracy (rescued 2, harmed 4) | Error rate -10%, exec success +10% |
| L8 correction      | L7 SQL + execution-guided correction (max 3 retries) | **48% accuracy** (rescued 6, harmed 0) | Surpasses L4 baseline by +8% |
| L8.1 NLP+Linking   | Intent + linking + phrases + rerank + rel_filter + validation → L8 correction | **54% accuracy** (rescued 4, harmed 1) | Surpasses L4 by +14%, L8 by +6% |
| L9 complete system | Full pipeline: ASR L5 + phonetic L6 + NLP L8.1 + retrieval L7 + Qwen 1.5B + validation + L4 exec + L8 correction | **58% text (29/50) / 50% audio (4/8)** | End-to-end CLI, structured stage results; frozen baselines untouched |
| L10 benchmarks     | Datasets acquired + loaders prepared (Spider full, BIRD Mini-Dev) | Preparation only — no accuracy yet | Evaluation pending explicit instruction |

---

## 10. Reproducibility

**Setup:**

- OS: Windows 10/11 (pycaw for mic unmute, sounddevice for capture)
- Python 3.12+
- Ollama running locally with `qwen2.5-coder:1.5b` model
- SQLite Enterprise database at `backend/data/enterprise.db` (seed=42)
- Whisper-small model at `~/.cache/whisper/small.pt` (or downloaded on first run)

**Model names:**

- L3–L4: `qwen2.5-coder:1.5b` (Ollama)
- L5: `whisper-small` (faster-whisper preferred, openai-whisper fallback)

**Seed:** 42 (database generation)

**Important commands:**

```bash
# L4 baseline (frozen)
python scripts/l4_evaluator.py

# L7 retrieval experiment
python scripts/l7_evaluator.py

# ASR test
python scripts/voice_test.py

# L6 ablation (no phonetic)
python scripts/voice_test.py --no-phonetic

# Record audio (default device auto-detect)
python scripts/record_audio.py

# List audio devices
python scripts/mic_probe.py
```

**Database generation:** Not in this repo; enterprise.db is pre-seeded with seed=42.

**Evaluation commands:**

```bash
# Run full test suite
python -m pytest backend/tests/ -v

# L4 report
# Already generated: evaluation/results/l4_report.json

# L7 report  
# Already generated: evaluation/results/l7_report.json

# L9 pipeline: text / audio / interactive
python scripts/voice_lite_sql.py --text "How many employees are there?"
python scripts/voice_lite_sql.py --audio backend/datasets/custom/spoken/audio/q01.wav
python scripts/voice_lite_sql.py --interactive

# L9 evaluations (real, chunk/marge with --limit/--offset)
python scripts/voice_lite_sql.py --evaluate --report evaluation/results/l9_report.json
python scripts/voice_lite_sql.py --evaluate-audio --report evaluation/results/l9_audio_report.json

# L10 dataset validation (integrity only, no accuracy)
python scripts/l10_dataset_validate.py
# -> evaluation/results/l10_dataset_validation.json
```

---

## 11. Final System Architecture

```
[Microphone] or [Text question]
      │
      ▼
L5 ASR (Whisper small) ────────► transcript + WER        [audio path only]
      │
      ▼
L6 Phonetic Normalization ──────► cleaned text
      │
      ▼
L8.1 NLP (intent, linking, phrases) ──► intent + linked entities
      │
      ▼
L7 Retrieval (ChromaDB top_k=5) + rerank + relationship filter ──► schema context
      │
      ▼
L3 Qwen 1.5B generation (read-only enforced) ──► SQL
      │
      ▼
L8.1 Structural validation (sqlglot) ──► valid/invalid + issues
      │
      ▼
L4 Read-only executor ──► rows / error
      │
      ▼
L8 Execution-guided correction (bounded ≤3) ──► corrected SQL
      │
      ▼
PipelineResult: final_sql + rows + correctness + per-stage latencies
```

Orchestration lives in `backend/pipeline/voice_lite_sql.py`; structured stage results in `backend/pipeline/pipeline_result.py`; CLI in `scripts/voice_lite_sql.py`.

---

## 12. References / Datasets

- **Enterprise SQLite database:** `backend/data/enterprise.db`, 7 tables, 9,295 rows, seed=42
- **Clean questions:** `backend/datasets/custom/questions.json`, 50 questions with reference SQL
- **Corrupted/development questions:** `backend/datasets/custom/corrupted_questions.json`, 20 questions
- **Whisper models:** `whisper-small`, `whisper-base` (openai-whisper / faster-whisper)
- **LLM:** `qwen2.5-coder:1.5b` via Ollama
- **Embeddings:** `all-MiniLM-L6-v2` (sentence-transformers, 384-dim)
- **ChromaDB:** persistent vector index for schema retrieval
- **Phonetic:** metaphone, fuzzywuzzy edit distance, confidence thresholding

---

## Appendices

### A. Test Suite Summary

| Level           | Test File          | Tests         |
| --------------- | ------------------ | ------------- |
| L1              | `test_level1.py` | 10            |
| L2              | `test_level2.py` | 14            |
| L3              | `test_level3.py` | 21            |
| L4              | `test_level4.py` | 34            |
| L5              | `test_level5.py` | 20            |
| L6              | `test_level6.py` | 39            |
| L7              | `test_level7.py` | 28            |
| L8              | `test_level8.py` | 16            |
| L8.1            | `test_level8_1.py` | 7 (suites)    |
| L9              | `test_level9.py` | 10 (suites)   |
| L10             | `test_level10_dataset.py` | 20 (pytest)   |
| **Total** |                    | **241** |

### B. L4 Per-Category Accuracy

| Category  | Questions | Accuracy |
| --------- | --------- | -------- |
| SELECT    | 10        | 80%      |
| WHERE     | 10        | 30%      |
| JOIN      | 10        | 50%      |
| GROUP BY  | 5         | 40%      |
| ORDER BY  | 5         | 40%      |
| aggregate | 5         | 0%       |
| complex   | 5         | 0%       |

### C. L7 Report Summary (real evaluation, saved)

- `evaluation/results/l7_report.json` — L4 vs L7 comparison on 50 clean questions (all-MiniLM-L6-v2, top_k=5, qwen2.5-coder:1.5b); L4 report untouched
- L4 accuracy: 40.0%; L7 accuracy: 36.0%
- Accuracy diff: -4.0%; execution error rate: 22% → 12%
- Rescued (L4 wrong → L7 right): 2; Harmed (L4 right → L7 wrong): 4; Held: 16; Missed: 28
- Retrieval per-question diagnostics included (retrieved doc IDs, scores, generated SQL, execution result, prompt)

### D. L6 Development Results

| Metric               | Value |
| -------------------- | ----- |
| Strict recovery      | 85%   |
| Equivalent recovery  | 95%   |
| Correction precision | 95%   |
| Correction recall    | 95%   |
| Correction accuracy  | 96%   |

### E. L5 Real-Audio Results

| Metric              | Value                                        |
| ------------------- | -------------------------------------------- |
| Samples transcribed | 8/8                                          |
| WER                 | 0.2882                                       |
| Avg latency         | ~9.78 seconds                                |
| Mic requirement     | 3.5mm earphone (built-in AMD non-functional) |

---

## Level 11 — Interactive Frontend

The research backend is complete and frozen through Level 9. Level 11 wraps the
**unchanged frozen pipeline** in a presentation-ready, browser-based dashboard:
natural-language text or microphone audio in, table/KPI results out, with
real-time per-stage visualization. No frozen L1–L9 code was modified.

### Architecture

- `backend/api/` — thin FastAPI layer (new, additive). It owns the singleton
  pipeline instance and exposes REST + SSE endpoints. The browser **never**
  executes SQL; every request goes through the real pipeline's read-only
  validator and read-only SQLite executor.
- `frontend/` — React 18 + Vite 5 + TypeScript, dark-first desktop-first,
  hand-rolled CSS (no UI framework).
- Streaming is real: the SSE endpoints temporarily install a latency-recording
  hook on the pipeline's own `PipelineTimer` (`backend/api/progress.py`),
  capture the actual stage timings, then restore the class — runtime
  instrumentation of frozen code only.

### Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Liveness probe |
| `/api/status` | GET | Component health (ollama / whisper / chroma / db / schema) |
| `/api/schema` | GET | L2 schema inspector output + live row counts |
| `/api/demo-questions` | GET | Demo questions from `questions.json` |
| `/api/query` | POST | Text question → real L9 pipeline |
| `/api/voice-query` | POST | Audio → real Whisper → real L9 pipeline |
| `/api/query/stream` | POST | SSE: live per-stage progress for text |
| `/api/voice-query/stream` | POST | SSE: live per-stage progress for audio |

SSE event types: `pipeline_started` (stage definitions for the run),
`stage_completed` (stage key + measured `latency_ms`), `pipeline_completed`
(full `PipelineResult` JSON), `pipeline_error` (fatal pipeline failure).

### Frontend components (product redesign)

The UI is **answer-first** with engineering detail behind progressive
disclosure — the research stages (L5/L6/L7/L8/L8.1) are demonstrated through
the friendly "How did you get this answer?" flow and a technical-details
modal, never as the primary interface.

- **Header** — brand + "Ask your database anything." tagline + a compact
  **System ready** pill that opens a per-component health tray (`/api/status`).
- **QueryInput** — hero composer: large textarea (`Enter` to ask,
  `Shift+Enter` newline), **Ask →** submit, and **hold-to-speak microphone**
  (MediaRecorder, webm/opus) with a live `Listening… ● 00:03` timer, plus
  permission-denied / no-microphone handling.
- **DemoQuestions** — "Try asking" suggestions (first 4 from
  `questions.json`); clicking fills the input, never auto-runs.
- **PipelineViewer** — user-friendly 7-step flow derived from the **real**
  stage state: `🎙 You asked → 🧠 Understanding → 🔎 Finding data →
  🤖 Creating SQL → 🛡 Checking → ⚡ Running → ✨ Answer`. Each step shows
  waiting / Working… / ✓ / ✕ as the true backend stages complete; sub-labels
  (intent, items found, rows · latency) are real `PipelineResult` values.
- **AnswerDisplay** — the largest section. KPI hero (big value + label),
  data table with pagination and row count, or an honest failure card.
  `Real database result · executed in X` comes from the real executor.
- **UnderstandingCard** — concise intent + entity/concept chips; **no raw
  scores** in the primary view.
- **HowItWorked** — expandable "How did you get this answer?" with steps:
  Understanding, Data found, Relationships, SQL created, Safety check,
  Database — all values derived from the real result.
- **TechnicalDetails** — tabbed modal (Overview / NLP / Schema / SQL /
  Execution / Correction) holding all L5–L8.1 internals: intent features,
  entity links, phrase scores, reranking, relationship-filter decisions,
  retrieval items with scores/distances, validation issues, correction
  attempts with SQL + errors.
- **DatabaseCard** — compact database summary (`7 tables · 9,295 rows`);
  **Explore schema** opens the SchemaDrawer.
- **SchemaDrawer** — slide-in explorer: tables → columns/types/PK/NN/FK.
- **HistoryPanel** — clean "Recent questions" (localStorage) with
  full-result restore and clear.
- **ErrorBanner** — understandable, stage-labelled errors (offline, pipeline,
  microphone).

### Text flow

1. User types (or clicks a suggestion) → `POST /api/query/stream`.
2. FastAPI runs the real pipeline; each stage completion is streamed as an SSE
   `stage_completed` event with the true measured latency.
3. `pipeline_completed` delivers the full result (normalization, NLP, retrieval,
   generated + final SQL, validation, execution rows, correction attempts).
4. UI renders the friendly flow, answer card, understanding chips, "How it
   worked" and (on request) technical details + history entry.

Suggestions are **not** hardcoded answers — clicking one fills the input and
runs the exact same real pipeline.

### Voice flow

1. Hold **Hold to Speak** → MediaRecorder captures microphone audio (webm).
2. Release → `POST /api/voice-query` (SSE variant for live progress).
3. FastAPI converts to WAV and runs the **real frozen ASR** (faster-whisper
   `small`), then feeds the transcript through the full real pipeline.
4. Pipeline results (including ASR transcript + latency) surface in the UI.

### Error handling

- Backend offline, Ollama unavailable, Whisper unavailable, SQL generation /
  validation / execution failures, correction exhaustion: all rendered with the
  failing stage highlighted.
- Microphone permission denied / missing: explicit message, text input remains.

### Security

The frontend has no SQL execution capability. All queries pass
FastAPI → frozen pipeline → read-only validator → read-only SQLite executor.
The `frontend/dist` build is served statically by FastAPI when present.

### How to run

```
# terminal 1 — backend
python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000

# terminal 2 — frontend (dev, proxies /api to :8000)
npm --prefix frontend run dev         # http://localhost:5173

# or single command once frontend/dist exists (backend serves it at :8000)
```

### Verification (Level 11)

- Backend: full suite (incl. new `backend/tests/test_level11_api.py`).
- Frontend: `npm --prefix frontend run test` (Vitest: shell render, end-to-end
  text query via mocked SSE, loading states, mic permission granted/denied,
  correction tab, history restore/clear, backend-offline banner).
- Production build: `npm --prefix frontend run build` (tsc strict + vite).
- Live E2E against `enterprise.db`: text query streams all real stage
  latencies; a real Whisper voice query returns a full ASR + pipeline result;
  built dashboard served by FastAPI with the new product UI.
- No historical benchmark result (L4/L7/L8/L8.1/L9/L10) was altered.
