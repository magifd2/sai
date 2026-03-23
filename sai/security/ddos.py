"""Rate limiter: per-user sliding window counters backed by DuckDB."""

import math
from dataclasses import dataclass

from ..db.repositories.rate_limit import RateLimitRepository
from ..utils.logging import get_logger
from ..utils.time import to_unix, utcnow

logger = get_logger(__name__)


@dataclass
class RateLimitResult:
    allowed: bool
    count_minute: int
    count_hour: int
    limit_minute: int
    limit_hour: int


class RateLimiter:
    def __init__(
        self,
        repo: RateLimitRepository,
        limit_per_minute: int = 10,
        limit_per_hour: int = 50,
    ) -> None:
        self._repo = repo
        self._limit_minute = limit_per_minute
        self._limit_hour = limit_per_hour

        # In-memory fast-path: {user_id: {window_start: count}}
        self._cache: dict[str, dict[float, int]] = {}

    def _minute_window(self, ts: float) -> float:
        """Floor timestamp to the current 60-second window."""
        return math.floor(ts / 60) * 60

    def _hour_window(self, ts: float) -> float:
        """Floor timestamp to the current 3600-second window."""
        return math.floor(ts / 3600) * 3600

    async def check_and_increment(self, user_id: str) -> RateLimitResult:
        """Increment counters and return allow/deny + current counts."""
        now = to_unix(utcnow())
        min_win = self._minute_window(now)
        hr_win = self._hour_window(now)

        count_min = await self._repo.increment(user_id, min_win)
        count_hr = await self._repo.increment(user_id, hr_win)

        allowed = count_min <= self._limit_minute and count_hr <= self._limit_hour

        if not allowed:
            logger.warning(
                "rate_limit.exceeded",
                user_id=user_id,
                count_min=count_min,
                count_hr=count_hr,
            )

        return RateLimitResult(
            allowed=allowed,
            count_minute=count_min,
            count_hour=count_hr,
            limit_minute=self._limit_minute,
            limit_hour=self._limit_hour,
        )

    async def cleanup(self) -> None:
        """Remove windows older than 2 hours."""
        cutoff = to_unix(utcnow()) - 7200
        await self._repo.cleanup(cutoff)
