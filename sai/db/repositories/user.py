"""UserRepository: user cache CRUD."""

from typing import Optional

from ...utils.time import from_unix, to_unix
from .base import BaseRepository
from pydantic import BaseModel


class UserRecord(BaseModel):
    user_id: str
    user_name: str
    display_name: Optional[str] = None
    is_bot: bool = False
    fetched_at: float  # Unix timestamp


class UserRepository(BaseRepository):

    async def get(self, user_id: str) -> Optional[UserRecord]:
        rows = await self._run(
            self._execute,
            "SELECT user_id, user_name, display_name, is_bot, fetched_at FROM users WHERE user_id = ?",
            [user_id],
        )
        if not rows:
            return None
        r = rows[0]
        return UserRecord(
            user_id=r[0], user_name=r[1], display_name=r[2],
            is_bot=bool(r[3]), fetched_at=r[4],
        )

    async def save(self, record: UserRecord) -> None:
        await self._run(self._save_sync, record)

    def _save_sync(self, record: UserRecord) -> None:
        self._execute(
            """
            INSERT OR REPLACE INTO users (user_id, user_name, display_name, is_bot, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [record.user_id, record.user_name, record.display_name, record.is_bot, record.fetched_at],
        )

    async def save_many(self, records: list[UserRecord]) -> None:
        await self._run(self._save_many_sync, records)

    def _save_many_sync(self, records: list[UserRecord]) -> None:
        self._executemany(
            "INSERT OR REPLACE INTO users (user_id, user_name, display_name, is_bot, fetched_at) VALUES (?,?,?,?,?)",
            [[r.user_id, r.user_name, r.display_name, r.is_bot, r.fetched_at] for r in records],
        )

    async def invalidate(self, user_id: str) -> None:
        """Mark a user as stale by setting fetched_at to 0."""
        await self._run(
            self._execute,
            "UPDATE users SET fetched_at = 0 WHERE user_id = ?",
            [user_id],
        )
