"""MemoryRepository: CRUD for memory_records and memory_archive."""

import json
from datetime import datetime
from typing import Optional

from ...memory.models import MemoryArchiveRecord, MemoryRecord, MemoryState
from ...utils.time import from_unix, to_unix
from .base import BaseRepository

# Explicit column list keeps row unpacking independent of schema column order
_COLS = (
    "id, user_id, user_name, channel_id, channel_name, "
    "ts, created_at, content, state, "
    "is_summary, summary_of, pinned_at, pinned_by, pin_reaction, "
    "nonce, embedding_id"
)
_SELECT = f"SELECT {_COLS} FROM memory_records"


def _row_to_record(row: tuple) -> MemoryRecord:
    (
        id_, user_id, user_name, channel_id, channel_name,
        ts, created_at, content, state,
        is_summary, summary_of, pinned_at, pinned_by, pin_reaction,
        nonce, embedding_id,
    ) = row
    return MemoryRecord(
        id=id_,
        user_id=user_id,
        user_name=user_name,
        channel_id=channel_id,
        channel_name=channel_name,
        ts=ts,
        created_at=from_unix(created_at),
        content=content,
        state=MemoryState(state),
        is_summary=bool(is_summary),
        summary_of=json.loads(summary_of) if summary_of else [],
        pinned_at=from_unix(pinned_at) if pinned_at else None,
        pinned_by=pinned_by,
        pin_reaction=pin_reaction,
        nonce=nonce,
        embedding_id=embedding_id,
    )


def _record_to_params(r: MemoryRecord) -> list:
    return [
        r.id, r.user_id, r.user_name, r.channel_id, r.channel_name,
        r.ts, to_unix(r.created_at), r.content, r.state.value,
        r.is_summary, json.dumps(r.summary_of) if r.summary_of else None,
        to_unix(r.pinned_at) if r.pinned_at else None,
        r.pinned_by, r.pin_reaction, r.nonce, r.embedding_id,
    ]


class MemoryRepository(BaseRepository):

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def save(self, record: MemoryRecord) -> None:
        """Insert or replace a memory record."""
        await self._run(self._save_sync, record)

    def _save_sync(self, record: MemoryRecord) -> None:
        self._execute(
            f"""
            INSERT OR REPLACE INTO memory_records ({_COLS})
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            _record_to_params(record),
        )

    async def save_many(self, records: list[MemoryRecord]) -> None:
        """Bulk insert/replace memory records."""
        await self._run(self._save_many_sync, records)

    def _save_many_sync(self, records: list[MemoryRecord]) -> None:
        self._executemany(
            f"INSERT OR REPLACE INTO memory_records ({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [_record_to_params(r) for r in records],
        )

    async def update_state(self, record_id: str, state: MemoryState) -> None:
        await self._run(self._update_state_sync, record_id, state)

    def _update_state_sync(self, record_id: str, state: MemoryState) -> None:
        self._execute(
            "UPDATE memory_records SET state = ? WHERE id = ?",
            [state.value, record_id],
        )

    async def update_embedding_id(self, record_id: str, embedding_id: str) -> None:
        await self._run(
            self._execute,
            "UPDATE memory_records SET embedding_id = ? WHERE id = ?",
            [embedding_id, record_id],
        )

    async def pin(
        self,
        record_id: str,
        pinned_by: str,
        pin_reaction: str,
        pinned_at: datetime,
    ) -> None:
        """Transition a record to PINNED state."""
        await self._run(self._pin_sync, record_id, pinned_by, pin_reaction, pinned_at)

    def _pin_sync(
        self,
        record_id: str,
        pinned_by: str,
        pin_reaction: str,
        pinned_at: datetime,
    ) -> None:
        self._execute(
            """
            UPDATE memory_records
               SET state = 'pinned',
                   pinned_at = ?,
                   pinned_by = ?,
                   pin_reaction = ?
             WHERE id = ?
            """,
            [to_unix(pinned_at), pinned_by, pin_reaction, record_id],
        )

    async def delete(self, record_id: str) -> None:
        await self._run(self._execute, "DELETE FROM memory_records WHERE id = ?", [record_id])

    async def delete_many(self, record_ids: list[str]) -> None:
        if not record_ids:
            return
        placeholders = ",".join("?" * len(record_ids))
        await self._run(
            self._execute,
            f"DELETE FROM memory_records WHERE id IN ({placeholders})",
            record_ids,
        )

    async def archive(self, record: MemoryRecord) -> None:
        """Move a record to memory_archive and delete from memory_records."""
        await self._run(self._archive_sync, record)

    def _archive_sync(self, record: MemoryRecord) -> None:
        from ...utils.time import utcnow
        now = to_unix(utcnow())
        self._execute(
            """
            INSERT OR IGNORE INTO memory_archive
                (id, user_id, user_name, channel_id, channel_name,
                 ts, created_at, archived_at, content, is_summary)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            [
                record.id, record.user_id, record.user_name,
                record.channel_id, record.channel_name,
                record.ts, to_unix(record.created_at), now,
                record.content, record.is_summary,
            ],
        )
        self._execute("DELETE FROM memory_records WHERE id = ?", [record.id])

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, record_id: str) -> Optional[MemoryRecord]:
        rows = await self._run(
            self._execute,
            f"{_SELECT} WHERE id = ?",
            [record_id],
        )
        return _row_to_record(rows[0]) if rows else None

    async def get_by_ts(self, ts: str, channel_id: str) -> Optional[MemoryRecord]:
        """Find a record by Slack message timestamp and channel."""
        rows = await self._run(
            self._execute,
            f"{_SELECT} WHERE ts = ? AND channel_id = ?",
            [ts, channel_id],
        )
        return _row_to_record(rows[0]) if rows else None

    async def find_by_state(
        self,
        state: MemoryState,
        limit: int = 500,
    ) -> list[MemoryRecord]:
        rows = await self._run(
            self._execute,
            f"{_SELECT} WHERE state = ? ORDER BY created_at ASC LIMIT ?",
            [state.value, limit],
        )
        return [_row_to_record(r) for r in rows]

    async def find_older_than(
        self,
        state: MemoryState,
        cutoff_unix: float,
        limit: int = 500,
    ) -> list[MemoryRecord]:
        """Return records in a given state older than the cutoff timestamp.
        PINNED records are never returned regardless of age."""
        rows = await self._run(
            self._execute,
            f"""
            {_SELECT}
             WHERE state = ? AND created_at < ?
             ORDER BY created_at ASC
             LIMIT ?
            """,
            [state.value, cutoff_unix, limit],
        )
        return [_row_to_record(r) for r in rows]

    async def count_hot_by_user(self, user_id: str) -> int:
        rows = await self._run(
            self._execute,
            "SELECT COUNT(*) FROM memory_records WHERE user_id = ? AND state = 'hot'",
            [user_id],
        )
        return int(rows[0][0]) if rows else 0

    async def find_recent(
        self,
        channel_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        if channel_id:
            rows = await self._run(
                self._execute,
                f"{_SELECT} WHERE channel_id = ? ORDER BY created_at DESC LIMIT ?",
                [channel_id, limit],
            )
        else:
            rows = await self._run(
                self._execute,
                f"{_SELECT} ORDER BY created_at DESC LIMIT ?",
                [limit],
            )
        return [_row_to_record(r) for r in rows]

    async def count_by_state(self) -> dict[str, int]:
        """Return record count per state."""
        rows = await self._run(
            self._execute,
            "SELECT state, COUNT(*) FROM memory_records GROUP BY state",
            [],
        )
        return {row[0]: int(row[1]) for row in rows}

    async def count_archive(self) -> int:
        """Return total number of archived records."""
        rows = await self._run(
            self._execute,
            "SELECT COUNT(*) FROM memory_archive",
            [],
        )
        return int(rows[0][0]) if rows else 0

    async def find_by_id_prefix(self, prefix: str) -> list[MemoryRecord]:
        """Return records whose ID starts with the given prefix."""
        rows = await self._run(
            self._execute,
            f"{_SELECT} WHERE id LIKE ?",
            [prefix + "%"],
        )
        return [_row_to_record(r) for r in rows]

    async def find_filtered(
        self,
        state: Optional[MemoryState] = None,
        user_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        """Return records matching optional filters, newest first."""
        where_parts: list[str] = []
        params: list = []
        if state:
            where_parts.append("state = ?")
            params.append(state.value)
        if user_id:
            where_parts.append("user_id = ?")
            params.append(user_id)
        if channel_id:
            where_parts.append("channel_id = ?")
            params.append(channel_id)
        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        params.append(limit)
        rows = await self._run(
            self._execute,
            f"{_SELECT} {where} ORDER BY created_at DESC LIMIT ?",
            params,
        )
        return [_row_to_record(r) for r in rows]
