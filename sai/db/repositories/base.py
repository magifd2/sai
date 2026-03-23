"""Base repository: hides DuckDB + asyncio.to_thread from callers."""

import asyncio
from typing import Any, Callable, TypeVar

from ..connection import connection_manager

T = TypeVar("T")


class BaseRepository:
    """
    All public methods of sub-repositories are async.
    Internally, synchronous DuckDB calls are offloaded to a thread pool
    via asyncio.to_thread so the event loop is never blocked.

    Sub-repositories should:
      - Define private _*_sync() methods containing DuckDB logic
      - Expose async public methods that call self._run(self._*_sync, ...)
      - Never call connection_manager directly outside this base class
    """

    def _execute(self, sql: str, params: list[Any] | None = None) -> list[Any]:
        """Execute a statement within the write lock and return fetchall."""
        with connection_manager.lock:
            if params:
                result = connection_manager.conn.execute(sql, params)
            else:
                result = connection_manager.conn.execute(sql)
            return result.fetchall()

    def _executemany(self, sql: str, params_seq: list[list[Any]]) -> None:
        """Execute a statement multiple times within the write lock."""
        with connection_manager.lock:
            connection_manager.conn.executemany(sql, params_seq)

    async def _run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Offload a synchronous DB function to a thread pool."""
        return await asyncio.to_thread(fn, *args, **kwargs)
