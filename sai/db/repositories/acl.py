"""ACLRepository: whitelist/blacklist persistence."""

from typing import Optional

from ...utils.time import to_unix, utcnow
from .base import BaseRepository
from pydantic import BaseModel


class ACLEntry(BaseModel):
    user_id: str
    list_type: str  # 'whitelist' | 'blacklist'
    added_at: float
    added_by: Optional[str] = None
    reason: Optional[str] = None


class ACLRepository(BaseRepository):

    async def add(
        self,
        user_id: str,
        list_type: str,
        added_by: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        now = to_unix(utcnow())
        await self._run(
            self._execute,
            """
            INSERT OR REPLACE INTO acl_entries (user_id, list_type, added_at, added_by, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            [user_id, list_type, now, added_by, reason],
        )

    async def remove(self, user_id: str, list_type: str) -> None:
        await self._run(
            self._execute,
            "DELETE FROM acl_entries WHERE user_id = ? AND list_type = ?",
            [user_id, list_type],
        )

    async def get(self, user_id: str, list_type: str) -> Optional[ACLEntry]:
        rows = await self._run(
            self._execute,
            "SELECT user_id, list_type, added_at, added_by, reason FROM acl_entries WHERE user_id = ? AND list_type = ?",
            [user_id, list_type],
        )
        if not rows:
            return None
        r = rows[0]
        return ACLEntry(user_id=r[0], list_type=r[1], added_at=r[2], added_by=r[3], reason=r[4])

    async def list_all(self, list_type: str) -> list[str]:
        """Return all user_ids in a given list."""
        rows = await self._run(
            self._execute,
            "SELECT user_id FROM acl_entries WHERE list_type = ?",
            [list_type],
        )
        return [r[0] for r in rows]

    async def is_in_list(self, user_id: str, list_type: str) -> bool:
        entry = await self.get(user_id, list_type)
        return entry is not None

    async def seed(self, user_ids: list[str], list_type: str) -> None:
        """Populate initial whitelist/blacklist entries from config (skip if already exists)."""
        now = to_unix(utcnow())
        for uid in user_ids:
            await self._run(
                self._execute,
                """
                INSERT OR IGNORE INTO acl_entries (user_id, list_type, added_at, added_by, reason)
                VALUES (?, ?, ?, 'system', 'seeded from config')
                """,
                [uid, list_type, now],
            )
