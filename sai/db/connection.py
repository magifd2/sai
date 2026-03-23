"""DuckDB connection management.

Provides a thread-safe connection pool for DuckDB.
DuckDB supports multiple readers via read_only connections, but only one
writer at a time. We use a single shared read-write connection protected
by a threading.Lock, and expose it only through the repository layer.
"""

import threading
from pathlib import Path
from typing import Optional

import duckdb


class _ConnectionManager:
    """Singleton that owns the DuckDB connection and a write lock."""

    def __init__(self) -> None:
        self._conn: Optional[duckdb.DuckDBPyConnection] = None
        self._lock = threading.Lock()
        self._db_path: Optional[str] = None

    def initialize(self, db_path: str) -> None:
        """Open (or create) the database file and install extensions."""
        if self._conn is not None:
            return  # already initialized

        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self._db_path = db_path
        self._conn = duckdb.connect(db_path)

        # Install and load the VSS (Vector Similarity Search) extension
        self._conn.execute("INSTALL vss;")
        self._conn.execute("LOAD vss;")
        # Required to persist HNSW indexes to disk (experimental in DuckDB VSS)
        self._conn.execute("SET hnsw_enable_experimental_persistence = true;")

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            raise RuntimeError("DB not initialized. Call connection_manager.initialize() first.")
        return self._conn

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# Module-level singleton — the only place DuckDB state lives
connection_manager = _ConnectionManager()
