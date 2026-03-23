"""Background scheduler for memory lifecycle transitions and process cleanup."""

import asyncio
from typing import Optional

from ..security.process_guard import ProcessGuard
from ..utils.logging import get_logger
from .lifecycle import LifecycleManager

logger = get_logger(__name__)

_PROCESS_GUARD_TICK = 5  # check for hung/zombie processes every 5 seconds


class MemoryScheduler:
    def __init__(
        self,
        lifecycle: LifecycleManager,
        process_guard: ProcessGuard,
        aging_interval_minutes: int = 30,
        archive_interval_hours: int = 6,
    ) -> None:
        self._lifecycle = lifecycle
        self._process_guard = process_guard
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
        process_guard_elapsed = 0
        tick = 5  # base tick: 5 seconds (drives process guard)

        while True:
            await asyncio.sleep(tick)
            aging_elapsed += tick
            archive_elapsed += tick
            process_guard_elapsed += tick

            # Process guard: kill hung processes and reap zombies
            if process_guard_elapsed >= _PROCESS_GUARD_TICK:
                process_guard_elapsed = 0
                try:
                    await asyncio.to_thread(self._process_guard.check_all)
                    await asyncio.to_thread(self._process_guard.cleanup_zombies)
                except Exception as exc:
                    logger.error("memory_scheduler.process_guard_error", error=str(exc))

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
