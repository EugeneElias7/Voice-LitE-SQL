#!/usr/bin/env python
"""Render startup script - seeds database if needed and starts the server."""

import os
import sys
from pathlib import Path

# Ensure we can import from backend
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import get_database_path, SEED_DB_ON_STARTUP
from backend.database.seed import build_database


def main():
    db_path = get_database_path()
    
    if SEED_DB_ON_STARTUP or not db_path.exists():
        print(f"Seeding database at {db_path}...")
        counts = build_database(str(db_path))
        print(f"Database seeded: {counts}")
    else:
        print(f"Using existing database at {db_path}")
    
    # Start the server
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    
    uvicorn.run(
        "backend.api.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()