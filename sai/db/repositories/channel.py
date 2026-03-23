"""ChannelRepository: channel cache CRUD."""

from typing import Optional

from .base import BaseRepository
from pydantic import BaseModel


class ChannelRecord(BaseModel):
    channel_id: str
    channel_name: str
    is_private: bool = False
    fetched_at: float  # Unix timestamp


class ChannelRepository(BaseRepository):

    async def get(self, channel_id: str) -> Optional[ChannelRecord]:
        rows = await self._run(
            self._execute,
            "SELECT channel_id, channel_name, is_private, fetched_at FROM channels WHERE channel_id = ?",
            [channel_id],
        )
        if not rows:
            return None
        r = rows[0]
        return ChannelRecord(
            channel_id=r[0], channel_name=r[1], is_private=bool(r[2]), fetched_at=r[3],
        )

    async def save(self, record: ChannelRecord) -> None:
        await self._run(self._save_sync, record)

    def _save_sync(self, record: ChannelRecord) -> None:
        self._execute(
            """
            INSERT OR REPLACE INTO channels (channel_id, channel_name, is_private, fetched_at)
            VALUES (?, ?, ?, ?)
            """,
            [record.channel_id, record.channel_name, record.is_private, record.fetched_at],
        )

    async def save_many(self, records: list[ChannelRecord]) -> None:
        await self._run(self._save_many_sync, records)

    def _save_many_sync(self, records: list[ChannelRecord]) -> None:
        self._executemany(
            "INSERT OR REPLACE INTO channels (channel_id, channel_name, is_private, fetched_at) VALUES (?,?,?,?)",
            [[r.channel_id, r.channel_name, r.is_private, r.fetched_at] for r in records],
        )

    async def invalidate(self, channel_id: str) -> None:
        await self._run(
            self._execute,
            "UPDATE channels SET fetched_at = 0 WHERE channel_id = ?",
            [channel_id],
        )
