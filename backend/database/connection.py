"""Voice-LitE-SQL -- Level 2: reusable SQLite connection abstraction.

Usage:

    with DatabaseConnection("path/to/database.db") as db:
        db.execute("SELECT ...")

Raises :class:`DatabaseError` for invalid or unusable database paths.
Foreign-key enforcement is enabled on every connection.
"""

import sqlite3
from pathlib import Path


class DatabaseError(Exception):
    """Raised when a database path is invalid or cannot be used."""


class DatabaseConnection:
    """A safe, reusable SQLite connection with foreign-key enforcement."""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self._connection = None

    @property
    def connection(self):
        """The underlying sqlite3.Connection (None until connected)."""
        return self._connection

    def connect(self):
        """Open the connection (idempotent) and enforce foreign keys."""
        if self._connection is not None:
            return self._connection
        if not self.db_path.exists():
            raise DatabaseError(f"database file not found: {self.db_path}")
        if not self.db_path.is_file():
            raise DatabaseError(f"database path is not a file: {self.db_path}")
        try:
            self._connection = sqlite3.connect(str(self.db_path))
            self._connection.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error as exc:
            self._connection = None
            raise DatabaseError(
                f"failed to open database '{self.db_path}': {exc}"
            ) from exc
        return self._connection

    def close(self):
        """Close the connection safely (idempotent)."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def cursor(self):
        """Return a cursor from the open connection."""
        return self.connect().cursor()

    def execute(self, sql, params=()):
        """Execute SQL on the open connection and return the cursor."""
        return self.connect().execute(sql, params)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
