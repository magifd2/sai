"""Database schema initialization.

Creates all tables and indexes on first run.
Safe to call on an existing database (uses CREATE TABLE IF NOT EXISTS).

Memory states:
  hot    - < 24h, full original content
  warm   - 1-7 days, LLM-summarized
  cold   - > 7 days, pending archive
  pinned - reaction-triggered, never aged or archived
"""

from .connection import connection_manager

# Default embedding dimension (text-embedding-nomic-embed-text-v1.5 produces 768-dim vectors)
_DEFAULT_EMBED_DIM = 768


def _build_ddl(embed_dim: int) -> str:
    return f"""
-- ----------------------------------------------------------------
-- Active memory records
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_records (
    id           VARCHAR PRIMARY KEY,
    user_id      VARCHAR NOT NULL,
    user_name    VARCHAR NOT NULL,
    channel_id   VARCHAR NOT NULL,
    channel_name VARCHAR,
    ts           VARCHAR NOT NULL,
    thread_ts    VARCHAR,           -- Thread root ts (NULL for top-level messages)
    created_at   DOUBLE NOT NULL,
    content      TEXT    NOT NULL,
    state        VARCHAR NOT NULL,
    is_summary   BOOLEAN NOT NULL DEFAULT false,
    summary_of   VARCHAR,           -- JSON array of source record IDs
    pinned_at    DOUBLE,
    pinned_by    VARCHAR,
    pin_reaction VARCHAR,
    nonce        VARCHAR,
    embedding_id VARCHAR,
    CHECK (state IN ('hot', 'warm', 'cold', 'pinned'))
);
CREATE INDEX IF NOT EXISTS idx_mem_state   ON memory_records (state);
CREATE INDEX IF NOT EXISTS idx_mem_user    ON memory_records (user_id);
CREATE INDEX IF NOT EXISTS idx_mem_time    ON memory_records (created_at);
CREATE INDEX IF NOT EXISTS idx_mem_ts      ON memory_records (ts);
CREATE INDEX IF NOT EXISTS idx_mem_channel ON memory_records (channel_id);
CREATE INDEX IF NOT EXISTS idx_mem_thread  ON memory_records (thread_ts);

-- ----------------------------------------------------------------
-- Archived records (cold storage)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_archive (
    id           VARCHAR PRIMARY KEY,
    user_id      VARCHAR NOT NULL,
    user_name    VARCHAR NOT NULL,
    channel_id   VARCHAR NOT NULL,
    channel_name VARCHAR,
    ts           VARCHAR NOT NULL,
    created_at   DOUBLE NOT NULL,
    archived_at  DOUBLE NOT NULL,
    content      TEXT    NOT NULL,
    is_summary   BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_arc_user ON memory_archive (user_id);
CREATE INDEX IF NOT EXISTS idx_arc_time ON memory_archive (created_at);

-- ----------------------------------------------------------------
-- Vector embeddings for RAG (VSS)
-- embedding_id links back to memory_records.embedding_id
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_embeddings (
    embedding_id VARCHAR PRIMARY KEY,
    record_id    VARCHAR NOT NULL,
    embedding    FLOAT[{embed_dim}] NOT NULL
);
-- HNSW index for approximate nearest-neighbour search
CREATE INDEX IF NOT EXISTS idx_embed_hnsw
    ON memory_embeddings
    USING HNSW (embedding)
    WITH (metric = 'cosine');

-- ----------------------------------------------------------------
-- User cache
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id      VARCHAR PRIMARY KEY,
    user_name    VARCHAR NOT NULL,
    display_name VARCHAR,
    is_bot       BOOLEAN NOT NULL DEFAULT false,
    fetched_at   DOUBLE  NOT NULL
);

-- ----------------------------------------------------------------
-- Channel cache
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS channels (
    channel_id   VARCHAR PRIMARY KEY,
    channel_name VARCHAR NOT NULL,
    is_private   BOOLEAN NOT NULL DEFAULT false,
    fetched_at   DOUBLE  NOT NULL
);

-- ----------------------------------------------------------------
-- Access control list
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS acl_entries (
    user_id   VARCHAR NOT NULL,
    list_type VARCHAR NOT NULL,
    added_at  DOUBLE  NOT NULL,
    added_by  VARCHAR,
    reason    VARCHAR,
    PRIMARY KEY (user_id, list_type),
    CHECK (list_type IN ('whitelist', 'blacklist'))
);

-- ----------------------------------------------------------------
-- Command execution audit log
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS command_log (
    id              VARCHAR PRIMARY KEY,
    user_id         VARCHAR NOT NULL,
    channel_id      VARCHAR NOT NULL,
    requested_at    DOUBLE  NOT NULL,
    nl_input        TEXT    NOT NULL,
    matched_command VARCHAR,
    script_path     VARCHAR,
    exit_code       INTEGER,
    stdout_snippet  TEXT,
    stderr_snippet  TEXT,
    nonce           VARCHAR NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cmd_user ON command_log (user_id);
CREATE INDEX IF NOT EXISTS idx_cmd_time ON command_log (requested_at);

-- ----------------------------------------------------------------
-- Rate limit tracking (sliding window counters)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rate_limits (
    user_id       VARCHAR NOT NULL,
    window_start  DOUBLE  NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, window_start)
);
CREATE INDEX IF NOT EXISTS idx_rate_user ON rate_limits (user_id);
"""


def _split_statements(sql: str) -> list[str]:
    """Split a multi-statement SQL string into individual statements."""
    statements = []
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            statements.append(stmt)
    return statements


def init_schema(embed_dim: int = _DEFAULT_EMBED_DIM) -> None:
    """Create all tables and indexes. Safe to call repeatedly."""
    conn = connection_manager.conn
    with connection_manager.lock:
        for stmt in _split_statements(_build_ddl(embed_dim)):
            conn.execute(stmt)
        # Migrations: add columns introduced after initial schema creation.
        # ALTER TABLE ADD COLUMN IF NOT EXISTS is idempotent in DuckDB.
        conn.execute(
            "ALTER TABLE memory_records ADD COLUMN IF NOT EXISTS thread_ts VARCHAR"
        )
