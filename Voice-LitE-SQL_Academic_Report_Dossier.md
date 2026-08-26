# Voice-LitE-SQL: A Lightweight, Speech-Enabled Natural Language to SQL Framework with Phonetic Normalization and Execution-Guided Self-Correction

**Running Title:** Voice-LitE-SQL

**Full Title:** Voice-LitE-SQL: A Lightweight, Speech-Enabled Natural Language to SQL Framework with Phonetic Normalization and Execution-Guided Self-Correction

**Author Name(s):**

- Eugene Elias (Reg. No. 2443119)
- Janhavi Srivastava (Reg. No. 2443125)

**Class:** 5 BCA B
**Subject:** Natural Language Processing

**Affiliation(s):**
Department of Computer Science
Christ (Deemed to be University)
Bangalore, Yeshwantpur
2026-27

**Under the Guidance of:**
Dr. Krishna Presannakumar
Department of Computer Science
Christ (Deemed to be University)
Bangalore, Yeshwantpur

**Corresponding Author (Email):**
[EMAIL_TO_BE_PROVIDED]

---

## Abstract (≤250 words)

Voice-LitE-SQL is a fully local, privacy-preserving speech-to-SQL system that transforms spoken natural language into executable SQL queries. The system addresses the critical challenge of Automatic Speech Recognition (ASR) errors corrupting schema identifiers (e.g., "sales"→"sails", "salary"→"celery") which catastrophically degrade Text-to-SQL accuracy. Our key innovation is a **Database-Aware Phonetic Normalization** layer (L6) that grounds ASR transcripts in the actual schema vocabulary using metaphone and fuzzy matching with conservative confidence gating. This is complemented by a **Relationship Necessity Filter** (L8.1) that distinguishes "foreign key exists" from "foreign key required for this query," preventing the small-model failure mode where available FK relationships induce spurious JOINs. The system integrates local Whisper-small ASR, ChromaDB schema retrieval, Qwen 2.5 Coder 1.5B generation, structural SQL validation, and execution-guided self-correction (≤3 retries) into a single pipeline orchestrated via structured stage diagnostics. On a controlled 50-question enterprise benchmark, the frozen L4 baseline achieves 40% execution accuracy; L7 retrieval reduces error rate (22%→12%) but lowers accuracy (36%); L8 correction surpasses baseline at 48% with zero harm; L8.1 NLP+schema-linking achieves 54% (+14% over baseline); L9 full pipeline achieves 58% text / 50% audio. Spider dev evaluation yields 39.85% on 1,034 questions. All processing is local (Ollama, Whisper, ChromaDB, SQLite); no cloud APIs. 252 tests pass.

**Keywords:** Speech-to-SQL, Phonetic Normalization, Small Language Models, Vector-based Schema Linking, Execution-Guided Self-Correction, Database Privacy

---

## 1. Introduction

### 1.1 Background of the Research Area

Natural Language to SQL (Text-to-SQL) parsing converts human language questions into structured database commands. While recent large language models achieve impressive results on clean text benchmarks, adding speech recognition introduces severe complications due to multi-modal input. Automatic Speech Recognition (ASR) models introduce acoustic typos—confusing "sales" with "sails," "salary" with "celery," "employees" with "employs"—which catastrophically degrade the schema linking process that grounds natural language to database structure.

### 1.2 Importance of the Selected Problem

In enterprise settings, non-technical stakeholders need intuitive access to database insights without writing SQL. Relying on proprietary cloud APIs for query processing raises critical data sovereignty concerns, as sensitive financial schemas must transit external APIs. Building a system that operates entirely on commodity hardware, processes noisy voice input robustly, and maintains data privacy is essential for trustworthy enterprise analytics.

### 1.3 Motivation for the Study

Existing systems typically cascade an ASR model directly into a Text-to-SQL model, causing **error compounding**—ASR errors propagate into schema hallucinations and execution failures. Full-schema prompting overwhelms small local models (1.5B parameters), causing table/column hallucinations. Retrieved schema (ChromaDB) introduces available foreign-key relationships that small models over-interpret as required JOINs. This study builds a staged, experimentally controlled pipeline where each level adds one measurable intervention while freezing all prior levels' code, model, and configuration.

### 1.4 Objectives of the Proposed Work

1. **L1–L2**: Establish a frozen data foundation (enterprise.db, 7 tables, 9,295 rows, seed=42) and a database-independent schema inspector.
2. **L3–L4**: Implement Qwen 2.5 Coder 1.5B text-to-SQL with schema-grounded prompting; freeze L4 baseline at 40% execution accuracy.
3. **L5**: Validate local Whisper-small ASR with real microphone input (WER=0.2882 on 8 samples).
4. **L6**: Implement Database-Aware Phonetic Normalization with frozen config (threshold=0.75, margin=0.12, metaphone=True, merge=True).
5. **L7**: Implement ChromaDB schema retrieval with relationship-aware FK expansion.
6. **L8**: Implement execution-guided self-correction (max 3 retries, no-blind-retry guard, zero-harm guarantee).
7. **L8.1**: Implement lightweight NLP/schema-linking: intent classification, schema/entity linking, phrase matching, candidate reranking, Relationship Necessity Filter, SQL structural validation.
8. **L9**: Integrate full pipeline (text + audio) with structured stage diagnostics; achieve 58% text / 50% audio accuracy.
9. **L10**: Prepare Spider/BIRD benchmark datasets (acquisition, loaders, per-DB indexes).

### 1.5 Research Questions

1. Does database-aware phonetic normalization improve execution accuracy under ASR noise?
2. Does schema retrieval reduce hallucinations in small models?
3. Can execution feedback recover accuracy from generated SQL errors?
4. Can lightweight NLP prevent spurious JOINs induced by retrieved FK relationships?
5. Can a 1.5B local model surpass the full-schema baseline (40%) without cloud APIs?

---

## 2. Related Work

| Ref | Title & Authors                                          | Venue/Year     | Dataset       | Research Gap                                   | Novelty                                          | Key Findings                                        | Limitations                                  |
| --- | -------------------------------------------------------- | -------------- | ------------- | ---------------------------------------------- | ------------------------------------------------ | --------------------------------------------------- | -------------------------------------------- |
| [1] | LitE-SQL: Lightweight Text-to-SQL (Piao et al.)          | EACL 2026      | BIRD, Spider  | Cloud LLM dependency; assumes clean text       | Vector retrieval + self-correction for 7B models | 7B local matches GPT-4 accuracy                     | Assumes clean text; vulnerable to ASR errors |
| [2] | Survey of Text-to-SQL in LLM Era (Liu et al.)            | IEEE TKDE 2025 | Spider, BIRD  | Gap in small vs large model comparison         | Comprehensive pipeline taxonomy                  | Execution feedback + data synthesis are bottlenecks | Survey; no novel architecture                |
| [3] | DBATI: Database-Aware ASR Error Correction (Shao et al.) | ICASSP 2023    | Spoken Spider | Cascade ASR errors ruin schema matching        | Phonetic distance mapping to schema              | Schema-aware correction improves accuracy           | Scales poorly to multi-table enterprise DBs  |
| [4] | Spider 2.0 (Dong et al.)                                 | arXiv 2024     | Spider 2.0    | Benchmarks don't reflect enterprise scale      | Enterprise benchmark with nested SQL             | Proprietary models drop on complex schemas          | Benchmark only; no parsing framework         |
| [5] | BIRD: Big Bench for Text-to-SQL (Li et al.)              | NeurIPS 2023   | BIRD          | Gap between academic and industrial benchmarks | 95 DBs, 37 domains, execution efficiency         | Execution accuracy needs grounded reasoning         | 33GB dataset resource-intensive locally      |

**Key Research Gaps Identified:**

1. **Gap 1**: Lightweight frameworks (LitE-SQL) assume clean text; no error-tolerant pipeline for ASR noise.
2. **Gap 2**: Enterprise voice analytics rely on cloud LLMs; no fully local pipeline with ASR + phonetic normalization + schema retrieval + self-correction.

---

## 3. Materials and Methods

### 3.1 Datasets

#### 3.1.1 Enterprise Dataset (Development, Controlled)

| Property                  | Value                                                                                                                                        |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **Database**        | `enterprise.db` (7 tables, 9,295 rows, seed=42)                                                                                            |
| **Tables**          | customers, departments, employees, locations, orders, products, sales                                                                        |
| **Foreign Keys**    | 7 (employees→departments, employees→employees, orders→customers, orders→employees, orders→products, sales→customers, sales→employees) |
| **Clean Questions** | 50 Q-SQL pairs (`questions.json`)                                                                                                          |
| **Corrupted/Dev**   | 20 pairs (`corrupted_queries.json`)                                                                                                        |
| **Spoken/Audio**    | 8 real WAV samples + manifest                                                                                                                |

#### 3.1.2 Spider (External Benchmark)

| Property            | Value                                             |
| ------------------- | ------------------------------------------------- |
| **Source**    | https://yale-lily.github.io/spider (CC BY-SA 4.0) |
| **Databases** | 166 train+dev + 206 test = 206 unique db_ids      |
| **Questions** | dev=1,034 (20 DBs) used for evaluation            |
| **License**   | CC BY-SA 4.0                                      |

#### 3.1.3 BIRD Mini-Dev

| Property            | Value                                                   |
| ------------------- | ------------------------------------------------------- |
| **Source**    | https://bird-bench.github.io/ (Non-commercial research) |
| **Databases** | 11 SQLite DBs                                           |
| **Questions** | 500 (dev split) with evidence + difficulty              |

### 3.2 Proposed Method

#### System Architecture (L9 Pipeline)

```
[Microphone] or [Text question]
      │
      ▼
L5 ASR (Whisper small) ──────► transcript + WER        [audio path only]
      │
      ▼
L6 Phonetic Normalization ───► cleaned text
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

#### Core Innovations

**L6: Database-Aware Phonetic Normalization**

- Schema-grounded vocabulary via L2 Schema Inspector (tables, columns, sub-words)
- Metaphone + Jaro-Winkler/Levenshtein similarity with frozen config:
  - `threshold=0.75`, `margin=0.12`, `high_confidence=0.85`, `metaphone=True`, `merge=True`
- Per-token `TokenDecision` audit trail (original, replacement, confidence, applied, strategy, reason, scores)

**L7: Relationship-Aware Schema Retrieval**

- Three document types: TABLE, COLUMN, RELATIONSHIP (FK edges)
- ChromaDB + `all-MiniLM-L6-v2` (384-dim, `local_files_only`)
- Deterministic FK expansion: column→FK edges, relationship→referenced column

**L8: Execution-Guided Self-Correction**

- Bounded retry loop (max 3), `seen_sql` set prevents blind retry
- Zero-harm guarantee: stops at first correct execution
- Correction prompt includes execution error + schema + reference result (eval only)

**L8.1: NLP + Schema-Linking (Key Innovation)**

- **Intent Classification**: 6 intents (SELECT, WHERE, JOIN, GROUP_BY, ORDER_BY, AGGREGATE, COMPLEX) via lexical patterns
- **Schema Linker**: Exact → normalized (singular/plural) → fuzzy (SequenceMatcher ≥0.75)
- **Phrase Matcher**: 2-4 gram n-grams + singular variants, token overlap scoring
- **Reranker**: 6 weighted signals (vector 0.30, lexical 0.20, phrase 0.20, intent 0.15, table 0.10, column 0.05)
- **Relationship Necessity Filter**: SELECT removes FK unless both tables explicitly mentioned
- **SQL Structure Validator**: sqlglot parse → unknown tables/cols, unnecessary JOINs, missing GROUP BY, intent compatibility

### 3.3 Experimental Setup

| Component                  | Configuration                                                       |
| -------------------------- | ------------------------------------------------------------------- |
| **LLM**              | Qwen 2.5 Coder 1.5B via Ollama (local)                              |
| **ASR**              | Whisper`small` (faster-whisper, CPU, int8)                        |
| **Embeddings**       | `all-MiniLM-L6-v2` (384-dim, `local_files_only=True`)           |
| **Vector DB**        | ChromaDB (persistent, cosine, deterministic IDs)                    |
| **SQL Parser**       | sqlglot (SQLite dialect)                                            |
| **Database**         | SQLite (`enterprise.db`, `mode=ro`, `query_only=ON`)          |
| **Fuzzy/Phonetic**   | jellyfish + rapidfuzz (Jaro-Winkler, Levenshtein, metaphone)        |
| **Read-Only Safety** | `mode=ro` URI; rejects non-SELECT/WITH; multi-statement rejection |

**Hardware**: Local only (Ollama + Whisper + ChromaDB + SQLite); no cloud APIs.

**Frozen Baselines**: L4=40% preserved untouched; all levels evaluated against it.

### 3.4 Evaluation Metrics

| Metric                             | Definition                                                                       |
| ---------------------------------- | -------------------------------------------------------------------------------- |
| **Execution Accuracy**       | % of questions where generated SQL executes and matches reference result exactly |
| **Execution Success Rate**   | % of questions where SQL executes without error                                  |
| **Generation Success Rate**  | % of questions where model produces syntactically valid SQL                      |
| **SQL Execution Error Rate** | % of questions where SQL execution fails                                         |
| **Rescued / Harmed**         | Questions previously incorrect→correct / previously correct→incorrect          |
| **Latency**                  | Per-stage and total wall-clock time (ms)                                         |

---

## 4. Results

### 4.1 Enterprise Benchmark (50 Clean Questions)

| Level          | Configuration                  | Exec Accuracy   | Correct/Total | Exec Success | SQL Error Rate | Rescued | Harmed |
| -------------- | ------------------------------ | --------------- | ------------- | ------------ | -------------- | ------- | ------ |
| **L4**   | Full schema → Qwen → execute | **40.0%** | 20/50         | 78%          | 22%            | —      | —     |
| **L5**   | Whisper-small + real mic       | 37.5% (audio)   | 3/8           | —           | —             | —      | —     |
| **L6**   | Phonetic (thresh=0.75)         | 37.5% (audio)   | 3/8           | —           | —             | 0       | 0      |
| **L7**   | ChromaDB top_k=5 + L4          | **36.0%** | 18/50         | 88%          | 12%            | 2       | 4      |
| **L8**   | L7 + correction (max 3)        | **48.0%** | 24/50         | 88%          | 12%            | 6       | 0      |
| **L8.1** | L8 + NLP+linking               | **54.0%** | 27/50         | 90%          | 10%            | 4       | 1      |
| **L9**   | Full pipeline (text)           | **58.0%** | 29/50         | —           | —             | —      | —     |
| **L9**   | Full pipeline (audio)          | **50.0%** | 4/8           | —           | —             | —      | —     |

### 4.2 Category-Level Accuracy Progression

| Category  | N  | L4  | L7  | L8  | L8.1 | L9   |
| --------- | -- | --- | --- | --- | ---- | ---- |
| SELECT    | 10 | 80% | 70% | 80% | 80%  | 70%  |
| WHERE     | 10 | 30% | 40% | 60% | 50%  | 50%  |
| JOIN      | 10 | 50% | 40% | 40% | 40%  | 50%  |
| GROUP BY  | 5  | 40% | 40% | 40% | 40%  | 80%  |
| ORDER BY  | 5  | 40% | 20% | 80% | 100% | 100% |
| aggregate | 5  | 0%  | 0%  | 0%  | 0%   | 0%   |
| complex   | 5  | 0%  | 0%  | 40% | 60%  | 60%  |

### 4.3 L5/L6 ASR Ablation (8 Real Audio Samples)

| Config        | WER    | Correct | Accuracy | Rescued | Harmed |
| ------------- | ------ | ------- | -------- | ------- | ------ |
| No phonetic   | 0.2882 | 3/8     | 37.5%    | 0       | 0      |
| With phonetic | 0.2882 | 3/8     | 37.5%    | 0       | 0      |

**Finding**: L6 phonetic normalization has **zero measurable end-to-end impact** on real audio (both 37.5%). Several failures are NOT speech problems (e.g., q05: WER=0 but SQL references nonexistent `location_id`).

### 4.4 L7/L8/L8.1 Rescue/Harm Analysis

| Level      | Rescued | Harmed | Held | Missed | Key Mechanism                               |
| ---------- | ------- | ------ | ---- | ------ | ------------------------------------------- |
| L7 vs L4   | 2       | 4      | 16   | 28     | FK expansion induces spurious JOINs         |
| L8 vs L7   | 6       | 0      | 18   | 26     | Exec feedback fixes missing cols; zero harm |
| L8.1 vs L8 | 4       | 1      | 23   | 22     | Rel-filter dominant (+10%)                  |

**Key Finding**: Relationship Necessity Filter = single largest contributor (+10%, 2 rescues, 0 harm).

### 4.4 L10 Spider Dev Evaluation (1,034 questions, 20 DBs)

| Metric                       | Value                        |
| ---------------------------- | ---------------------------- |
| **Execution Accuracy** | **39.85%** (412/1,034) |
| Generation Success           | 99.81%                       |
| Execution Success            | 67.6%                        |
| SQL Error Rate               | 32.4%                        |
| Median Latency               | 6.7 s/q                      |
| Correction Rescued / Harmed  | 35 / 0                       |

### 4.5 L5/L6 ASR Performance

| Metric              | Value                                        |
| ------------------- | -------------------------------------------- |
| Samples Transcribed | 8/8                                          |
| Average WER         | 0.2882                                       |
| Average Latency     | 9.78 seconds                                 |
| Model               | Whisper`small` (faster-whisper, int8, CPU) |

### 4.6 L6 Phonetic Normalization (Development Set, 20 pairs)

| Metric               | Value |
| -------------------- | ----- |
| Strict Recovery      | 85%   |
| Equivalent Recovery  | 95%   |
| Correction Precision | 95%   |
| Correction Recall    | 95%   |
| Correction Accuracy  | 96%   |

**Ablations**: Without phonetic encoding (accuracy 94%), without multi-word merge (accuracy 88%).

---

## 5. Discussions

### 5.1 L7 — Why Schema Retrieval Initially Reduced Accuracy

L7 accuracy (36%) < L4 baseline (40%) because **relationship expansion** surfaces FK edges that induce spurious JOINs in the 1.5B model on simple single-table questions (harm cases: q03, q04, q30, q37). However, retrieval **reduces SQL error rate** (22%→12%) and improves execution success (78%→88%), showing it reduces generation-time hallucinations. The JOIN over-engagement cost more correct answers than the 2 rescues gained.

### 5.2 L8 — Execution-Guided Correction Surpasses Baseline

L8 achieves **48%** (+8% over L4) with **zero harm**. The loop stops at attempt 1 when original SQL is correct, guaranteeing zero regression. Rescues occur on "executable but incorrect" SQL (missing columns in WHERE/ORDER BY, wrong aggregate columns). The "no progress" guard stops blind retries when the model echoes the same hallucinated JOIN (26 missed cases). Complex queries (q46, q47) rescued for the first time.

### 5.3 L8.1 — NLP/Schema-Linking Optimization

**Relationship Necessity Filter = dominant gain** (+10% in 10-q ablation, 2 rescues, 0 harm). It prevents "available FK → assumed JOIN" by filtering FK edges unless both tables are explicitly referenced in the question. ORDER BY and Complex categories show largest gains (+20% each vs L8) due to structural validation catching missing columns/aliases. Aggregate category remains 0% (requires query decomposition).

### 5.4 L6 Phonetic Normalization: Dev vs Real Audio

L6 shows **85% strict recovery on development set** but **zero end-to-end gain on real audio** (37.5% both ±phonetic). Key reason: several failures are NOT speech problems (e.g., q05 has WER=0 but SQL references nonexistent `location_id`—a schema hallucination, not ASR error). L6 cannot overcome L4's core hallucination problem.

### 5.5 Spider Dev Evaluation (External Benchmark)

Frozen L9 pipeline achieves **39.85% execution accuracy** on Spider dev (1,034 questions, 20 DBs). Generation success 99.81%, execution success 67.6%, error rate 32.4%, median latency 6.7s. Correction rescued 35, harmed 0. Performance varies significantly by database (16%–80% accuracy).

---

## 4.7 Latency Analysis (L9 Text Pipeline)

| Stage                 | Mean  | Median |
| --------------------- | ----- | ------ |
| Total                 | 12.4s | 11.8s  |
| Generation (Qwen)     | 5.1s  | 5.0s   |
| Retrieval (ChromaDB)  | 1.7s* | 45ms   |
| Correction (when run) | 5.6s  | 5.7s   |
| NLP                   | 24ms  | 22ms   |
| Execution             | 23ms  | 4ms    |

*First-query embedder/index warm-up inflates retrieval mean; steady-state retrieval is ~45ms.

---

## 6. Conclusion

Voice-LitE-SQL demonstrates that a **fully local, staged pipeline** can surpass the full-schema Text-to-SQL baseline (40% → 58% text / 50% audio) using a **1.5B parameter model** with zero cloud APIs. The critical innovations are:

1. **Database-Aware Phonetic Normalization (L6)**: Schema-grounded metaphone+fuzzy correction with frozen conservative gating.
2. **Relationship Necessity Filter (L8.1)**: Distinguishes "FK exists" from "FK required," preventing spurious JOINs (+10% accuracy, zero harm).
3. **Execution-Guided Self-Correction (L8)**: Bounded retry with execution feedback, zero-harm guarantee, no-blind-retry guard.
4. **Frozen Baseline Methodology**: L4=40% preserved untouched; every level evaluated against it.

**Limitations**: Aggregate category 0% (needs query decomposition); small real-audio eval (8 samples); L6 no real-audio gain; L10 Spider 39.85% < enterprise 58%; 12s latency dominated by Qwen generation.

**Future Work**: Larger local models (7B/14B); query decomposition for aggregates; BIRD evaluation; Spoken Spider acquisition; larger ASR evaluation (≥50 samples); value-phrase interpretation ("fifty dollars"→50).

---

## References

1. Piao, S., Lee, J., & Park, S. (2026). LitE-SQL: A Lightweight and Efficient Text-to-SQL Framework with Vector-based Schema Linking and Execution-Guided Self-Correction. *Findings of the Association for Computational Linguistics: EACL 2026*.
2. Liu, Y. et al. (2025). A Survey of Text-to-SQL in the Era of Large Language Models. *IEEE Transactions on Knowledge and Data Engineering (TKDE)*.
3. Shao, Y. et al. (2023). Database-Aware ASR Error Correction for Speech-to-SQL Parsing. *IEEE International Conference on Acoustics, Speech and Signal Processing (ICASSP)*.
4. Dong, F. et al. (2024). Spider 2.0: Evaluating Language Models on Enterprise Text-to-SQL Workflows. *arXiv:2411.07763*.
5. Li, J. et al. (2023). BIRD: A Big Bench for Large-Scale Database Grounded Text-to-SQLs. *Advances in Neural Information Processing Systems (NeurIPS)*.
6. Yu, T. et al. (2018). Spider: A Large-Scale Human-Labeled Dataset for Complex Text-to-SQL. *EMNLP 2018*. DOI: 10.18653/v1/D18-1425.
7. Radford, A. et al. (2022). Robust Speech Recognition via Large-Scale Weak Supervision. *ICML 2022*.
8. Systran. (2023). faster-whisper. GitHub: https://github.com/SYSTRAN/faster-whisper
9. Qwen Team. (2024). Qwen2.5-Coder: Technical Report. *arXiv:2409.12193*.
10. Reimers, N. & Gurevych, I. (2019). Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks. *EMNLP 2019*. DOI: 10.18653/v1/D19-1410.
11. Scholak, Y. et al. (2021). PICARD: Parsing Incrementally for Constrained Auto-Regressive Decoding from SQL. *EMNLP 2021*. DOI: 10.18653/v1/2021.emnlp-main.712.
12. Hwang, W. et al. (2019). Comprehensive Study on Text-to-SQL. *arXiv:1908.08113*.
13. SQLite Consortium. (2024). SQLite Documentation: URI Filenames. https://www.sqlite.org/uri.html
14. sqlglot Team. (2023). sqlglot: SQL Parser and Transpiler. GitHub: https://github.com/tobymao/sqlglot

---

## Appendix: Test Suite Summary (252 Tests Total)

| Level           | Test File                   | Tests         |
| --------------- | --------------------------- | ------------- |
| L1              | `test_level1.py`          | 10            |
| L2              | `test_level2.py`          | 14            |
| L3              | `test_level3.py`          | 21            |
| L4              | `test_level4.py`          | 34            |
| L5              | `test_level5.py`          | 20            |
| L6              | `test_level6.py`          | 39            |
| L7              | `test_level7.py`          | 28            |
| L8              | `test_level8.py`          | 23            |
| L8.1            | `test_level8_1.py`        | 7 (suites)    |
| L9              | `test_level9.py`          | 10 (suites)   |
| L10             | `test_level10_dataset.py` | 20            |
| **Total** |                             | **252** |

All 252 tests pass. Frontend: 21 tests pass (Vitest).

---

*Document prepared for academic submission — Voice-LitE-SQL project dossier*
*Last updated: 2026*
*All results extracted from frozen evaluation reports in `evaluation/results/`*
