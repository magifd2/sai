"""CommandLogRepository: audit log for command executions."""

from typing import Optional

from pydantic import BaseModel

from ...utils.ids import new_id
from ...utils.time import to_unix, utcnow
from .base import BaseRepository

_COLS = (
    "id, user_id, channel_id, requested_at, nl_input, "
    "matched_command, script_path, exit_code, "
    "stdout_snippet, stderr_snippet, nonce"
)
_SELECT = f"SELECT {_COLS} FROM command_log"


class CommandLogEntry(BaseModel):
    id: str
    user_id: str
    channel_id: str
    requested_at: float
    nl_input: str
    matched_command: Optional[str] = None
    script_path: Optional[str] = None
    exit_code: Optional[int] = None
    stdout_snippet: Optional[str] = None
    stderr_snippet: Optional[str] = None
    nonce: str


class CommandLogRepository(BaseRepository):

    async def log(
        self,
        user_id: str,
        channel_id: str,
        nl_input: str,
        nonce: str,
        matched_command: Optional[str] = None,
        script_path: Optional[str] = None,
        exit_code: Optional[int] = None,
        stdout_snippet: Optional[str] = None,
        stderr_snippet: Optional[str] = None,
    ) -> str:
        """Write an audit log entry. Returns the new entry ID."""
        entry_id = new_id()
        now = to_unix(utcnow())
        await self._run(
            self._execute,
            """
            INSERT INTO command_log
                (id, user_id, channel_id, requested_at, nl_input,
                 matched_command, script_path, exit_code,
                 stdout_snippet, stderr_snippet, nonce)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                entry_id, user_id, channel_id, now, nl_input,
                matched_command, script_path, exit_code,
                stdout_snippet, stderr_snippet, nonce,
            ],
        )
        return entry_id

    async def recent(self, user_id: str, limit: int = 20) -> list[CommandLogEntry]:
        rows = await self._run(
            self._execute,
            f"{_SELECT} WHERE user_id = ? ORDER BY requested_at DESC LIMIT ?",
            [user_id, limit],
        )
        return [
            CommandLogEntry(
                id=r[0], user_id=r[1], channel_id=r[2], requested_at=r[3],
                nl_input=r[4], matched_command=r[5], script_path=r[6],
                exit_code=r[7], stdout_snippet=r[8], stderr_snippet=r[9], nonce=r[10],
            )
            for r in rows
        ]
