"""Voice-LitE-SQL -- Configuration management.

Centralizes all paths and settings, using environment variables with sensible defaults.
Works on both Windows (local dev) and Linux (Render/production).
"""

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Database
DEFAULT_DB_PATH = PROJECT_ROOT / "backend" / "data" / "enterprise.db"
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", str(DEFAULT_DB_PATH)))

# Questions dataset
QUESTIONS_PATH = PROJECT_ROOT / "backend" / "datasets" / "custom" / "questions.json"

# ChromaDB index directory
INDEX_DIR = Path(os.environ.get("INDEX_DIR", str(PROJECT_ROOT / "evaluation" / "index")))

# Reports directory
REPORTS_DIR = PROJECT_ROOT / "evaluation" / "results"

# Schema retrieval
DEFAULT_EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
DEFAULT_TOP_K = int(os.environ.get("TOP_K", "5"))

# LLM
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5-coder:1.5b")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))

# Ollama specific
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# OpenAI specific
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

# Anthropic specific
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

# OpenRouter specific
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# ASR
ASR_MODEL = os.environ.get("ASR_MODEL", "small")
ASR_BACKEND = os.environ.get("ASR_BACKEND", "faster-whisper")

# Pipeline
PIPELINE_MAX_CORRECTION_ATTEMPTS = int(os.environ.get("MAX_CORRECTION_ATTEMPTS", "3"))
PIPELINE_CORRECTION_TIMEOUT = int(os.environ.get("CORRECTION_TIMEOUT", "120"))

# Render-specific: seed database at startup if needed
SEED_DB_ON_STARTUP = os.environ.get("SEED_DB_ON_STARTUP", "false").lower() == "true"

# Server
SERVER_HOST = os.environ.get("HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("PORT", "8000"))

# Frontend
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def ensure_directories():
    """Create required directories if they don't exist."""
    directories = [
        DATABASE_PATH.parent,
        INDEX_DIR,
        REPORTS_DIR,
    ]
    for d in directories:
        d.mkdir(parents=True, exist_ok=True)


def get_database_path() -> Path:
    """Get the database path, ensuring parent directory exists."""
    ensure_directories()
    return DATABASE_PATH


def get_index_dir() -> Path:
    """Get the ChromaDB index directory."""
    ensure_directories()
    return INDEX_DIR


def get_reports_dir() -> Path:
    """Get the evaluation reports directory."""
    ensure_directories()
    return REPORTS_DIR