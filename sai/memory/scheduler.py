"""Background scheduler for memory lifecycle transitions."""

import asyncio
from typing import Optional

from ..utils.logging import get_logger
from .lifecycle import LifecycleManager

logger = get_logger(__name__)


class MemoryScheduler:
    def __init__(
        self,
        lifecycle: LifecycleManager,
        aging_interval_minutes: int = 30,
        archive_interval_hours: int = 6,
    ) -> None:
        self._lifecycle = lifecycle
        self._aging_interval = aging_interval_minutes * 60
        self._archive_interval = archive_interval_hours * 3600
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        logger.info(
            "memory_scheduler.started",
            aging_interval_s=self._aging_interval,
            archive_interval_s=self._archive_interval,
        )

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            logger.info("memory_scheduler.stopped")

    async def _run(self) -> None:
        aging_elapsed = 0
        archive_elapsed = 0
        tick = 60  # check every 60 seconds

        while True:
            await asyncio.sleep(tick)
            aging_elapsed += tick
            archive_elapsed += tick

            if aging_elapsed >= self._aging_interval:
                aging_elapsed = 0
                try:
                    stats = await self._lifecycle.run_aging()
                    logger.info("memory_scheduler.aging_cycle", **stats)
                except Exception as exc:
                    logger.error("memory_scheduler.aging_error", error=str(exc))

            if archive_elapsed >= self._archive_interval:
                archive_elapsed = 0
                try:
                    count = await self._lifecycle.run_archive()
                    logger.info("memory_scheduler.archive_cycle", archived=count)
                except Exception as exc:
                    logger.error("memory_scheduler.archive_error", error=str(exc))
