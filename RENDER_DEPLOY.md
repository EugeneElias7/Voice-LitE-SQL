# Voice-LitE-SQL Render Deployment Guide

## Quick Deploy to Render

1. **Fork/Clone this repo to GitHub**

2. **Create a new Web Service on Render:**
   - Connect your GitHub repo
   - Render will auto-detect `render.yaml`
   - Or manually configure:
     - **Build Command:** `pip install -r requirements.txt`
     - **Start Command:** `python start_server.py`
     - **Python Version:** 3.11

3. **Set Environment Variables in Render Dashboard:**
   ```
   LLM_PROVIDER=openai
   LLM_MODEL=gpt-4o-mini
   OPENAI_API_KEY=<your-key>  # Mark as secret
   EMBEDDING_MODEL=all-MiniLM-L6-v2
   DATABASE_PATH=/opt/render/project/src/backend/data/enterprise.db
   INDEX_DIR=/opt/render/project/src/evaluation/index
   SEED_DB_ON_STARTUP=true
   ```

4. **Deploy!** The database will be seeded on first startup.

## LLM Provider Options

| Provider | LLM_PROVIDER | LLM_MODEL Example | Required Env Vars |
|----------|--------------|-------------------|-------------------|
| OpenAI | `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `claude-3-haiku-20240307` | `ANTHROPIC_API_KEY` |
| OpenRouter | `openrouter` | `anthropic/claude-3-haiku` | `OPENROUTER_API_KEY` |
| Ollama (local only) | `ollama` | `qwen2.5-coder:1.5b` | `OLLAMA_HOST` |

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Seed database (first time only)
python -m backend.database.seed

# Run API server
python start_server.py
# or
uvicorn backend.api.main:app --reload

# Run tests
python -m pytest backend/tests/ -v

# Run L8.1 evaluation (full 50 questions)
python scripts/l8_1_evaluator.py

# Run ablation study
python scripts/l8_1_evaluator.py --run-ablations
```

## Architecture Summary

```
Voice Input → ASR (Whisper) → L6 Normalization → L8.1 NLP
    ↓
Intent Classification → Entity Linking → Phrase Matching
    ↓
L7 Vector Retrieval → Candidate Reranking → Relationship Filter
    ↓
Qwen 1.5B / OpenAI / Anthropic → SQL Generation
    ↓
SQL Structural Validation → L4 Read-Only Execution
    ↓
L8 Execution-Guided Correction (max 3 retries)
    ↓
Result
```

## Results (50 questions, Qwen 1.5B)

| Level | Accuracy | vs L4 |
|-------|----------|-------|
| L4 (frozen) | 40% | — |
| L7 | 36% | -4% |
| L8 | 48% | +8% |
| **L8.1** | **64%** | **+24%** |

**Category breakthroughs:**
- WHERE: 30% → 70%
- JOIN: 50% → 60%
- GROUP BY: 40% → 60%
- aggregate: 0% → 20% (first time!)
- complex: 0% → 60% (first time!)

## Files Added for L8.1

```
backend/
  config.py                 # Centralized configuration
  nlp/
    __init__.py
    intent_classifier.py    # 7-category intent detection
    schema_linker.py        # Exact/normalized/fuzzy entity linking
    phrase_matcher.py       # Multi-word phrases + concepts
  retrieval/
    reranker.py             # Multi-signal candidate reranking
    relationship_filter.py  # Available vs required FKs
  validation/
    sql_structure_validator.py  # sqlglot-based validation
  llm/
    unified_client.py       # Ollama/OpenAI/Anthropic/OpenRouter
scripts/
  l8_1_evaluator.py         # Full evaluator with ablation flags
backend/tests/
  test_level8_1.py          # 6 component tests
```