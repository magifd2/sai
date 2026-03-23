"""RateLimitRepository: sliding window counters."""

from .base import BaseRepository


class RateLimitRepository(BaseRepository):

    async def increment(self, user_id: str, window_start: float) -> int:
        """Increment counter for this user/window and return the new count."""
        return await self._run(self._increment_sync, user_id, window_start)

    def _increment_sync(self, user_id: str, window_start: float) -> int:
        # Upsert: insert with count=1, or increment existing
        self._execute(
            """
            INSERT INTO rate_limits (user_id, window_start, request_count)
            VALUES (?, ?, 1)
            ON CONFLICT (user_id, window_start)
            DO UPDATE SET request_count = request_count + 1
            """,
            [user_id, window_start],
        )
        rows = self._execute(
            "SELECT request_count FROM rate_limits WHERE user_id = ? AND window_start = ?",
            [user_id, window_start],
        )
        return int(rows[0][0]) if rows else 1

    async def get_count(self, user_id: str, window_start: float) -> int:
        rows = await self._run(
            self._execute,
            "SELECT request_count FROM rate_limits WHERE user_id = ? AND window_start = ?",
            [user_id, window_start],
        )
        return int(rows[0][0]) if rows else 0

    async def cleanup(self, older_than: float) -> None:
        """Delete rate limit windows older than the given Unix timestamp."""
        await self._run(
            self._execute,
            "DELETE FROM rate_limits WHERE window_start < ?",
            [older_than],
        )
