"""Initialize the SAI SQLite database schema.

Usage:
    uv run python scripts/setup_db.py [--db-path PATH]
"""

import asyncio
import sys
from pathlib import Path

import aiosqlite
import click

# Memory states:
#   hot    - < 24h, full original content
#   warm   - 1-7 days, LLM-summarized
#   cold   - > 7 days, pending archive
#   pinned - reaction-triggered, never aged or archived

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ----------------------------------------------------------------
-- Active memory records
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_records (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    user_name       TEXT NOT NULL,
    channel_id      TEXT NOT NULL,
    channel_name    TEXT,
    ts              TEXT NOT NULL,
    created_at      REAL NOT NULL,
    content         TEXT NOT NULL,
    state           TEXT NOT NULL
                    CHECK(state IN ('hot','warm','cold','pinned')),
    is_summary      INTEGER NOT NULL DEFAULT 0,
    summary_of      TEXT,               -- JSON array of source record IDs
    pinned_at       REAL,               -- set when state transitions to pinned
    pinned_by       TEXT,               -- user_id of the person who added the reaction
    pin_reaction    TEXT,               -- the reaction name that triggered pinning
    nonce           TEXT,
    embedding_id    TEXT
);
CREATE INDEX IF NOT EXISTS idx_memory_state    ON memory_records(state);
CREATE INDEX IF NOT EXISTS idx_memory_user     ON memory_records(user_id);
CREATE INDEX IF NOT EXISTS idx_memory_time     ON memory_records(created_at);
CREATE INDEX IF NOT EXISTS idx_memory_ts       ON memory_records(ts);
CREATE INDEX IF NOT EXISTS idx_memory_channel  ON memory_records(channel_id);

-- ----------------------------------------------------------------
-- Archived records (cold storage, separate table)
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_archive (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    user_name       TEXT NOT NULL,
    channel_id      TEXT NOT NULL,
    channel_name    TEXT,
    ts              TEXT NOT NULL,
    created_at      REAL NOT NULL,
    archived_at     REAL NOT NULL,
    content         TEXT NOT NULL,
    is_summary      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_archive_user    ON memory_archive(user_id);
CREATE INDEX IF NOT EXISTS idx_archive_time    ON memory_archive(created_at);

-- ----------------------------------------------------------------
-- User cache
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,
    user_name       TEXT NOT NULL,
    display_name    TEXT,
    is_bot          INTEGER NOT NULL DEFAULT 0,
    fetched_at      REAL NOT NULL
);

-- ----------------------------------------------------------------
-- Channel cache
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS channels (
    channel_id      TEXT PRIMARY KEY,
    channel_name    TEXT NOT NULL,
    is_private      INTEGER NOT NULL DEFAULT 0,
    fetched_at      REAL NOT NULL
);

-- ----------------------------------------------------------------
-- Access control list
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS acl_entries (
    user_id         TEXT NOT NULL,
    list_type       TEXT NOT NULL CHECK(list_type IN ('whitelist','blacklist')),
    added_at        REAL NOT NULL,
    added_by        TEXT,
    reason          TEXT,
    PRIMARY KEY(user_id, list_type)
);

-- ----------------------------------------------------------------
-- Command execution audit log
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS command_log (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    channel_id      TEXT NOT NULL,
    requested_at    REAL NOT NULL,
    nl_input        TEXT NOT NULL,
    matched_command TEXT,
    script_path     TEXT,
    exit_code       INTEGER,
    stdout_snippet  TEXT,
    stderr_snippet  TEXT,
    nonce           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cmdlog_user     ON command_log(user_id);
CREATE INDEX IF NOT EXISTS idx_cmdlog_time     ON command_log(requested_at);

-- ----------------------------------------------------------------
-- Rate limit tracking
-- ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rate_limits (
    user_id         TEXT NOT NULL,
    window_start    REAL NOT NULL,
    request_count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(user_id, window_start)
);
CREATE INDEX IF NOT EXISTS idx_ratelimit_user  ON rate_limits(user_id);
"""


async def init_db(db_path: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA)
        await db.commit()
    print(f"Database initialized at: {path.resolve()}")


@click.command()
@click.option("--db-path", default="./data/sai.db", help="Path to SQLite database file")
def main(db_path: str) -> None:
    """Initialize the SAI database schema."""
    asyncio.run(init_db(db_path))


if __name__ == "__main__":
    main()
