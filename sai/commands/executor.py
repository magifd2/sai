"""Command executor: run pre-registered shell scripts with sandboxing.

Parameters are passed to scripts via JSON on stdin (never as CLI arguments).
This prevents shell injection through argument values and keeps the interface
clean regardless of argument types or content.

stdin JSON format:
    {
        "user_id": "U123456",
        "command": "command_name",
        "args": {
            "arg1": "value1",
            "arg2": "value2"
        }
    }
"""

import json
import os
import resource
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..security.process_guard import ProcessGuard
from ..utils.logging import get_logger
from .registry import CommandDefinition, CommandRegistry

logger = get_logger(__name__)

_SAFE_ENV_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "TZ"}
_MAX_OUTPUT_BYTES = 4096


@dataclass
class ExecutionResult:
    command_name: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def format_for_slack(self, max_chars: int = 4000) -> str:
        """Format output as a Slack-safe code block."""
        if self.timed_out:
            return f":warning: Command `{self.command_name}` timed out."
        if not self.success:
            body = (self.stderr or self.stdout or "(no output)")[:max_chars]
            return f":x: Command `{self.command_name}` failed (exit {self.exit_code}):\n```\n{body}\n```"
        body = (self.stdout or "(no output)")[:max_chars]
        return f":white_check_mark: `{self.command_name}`:\n```\n{body}\n```"


def _safe_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}


def _set_resource_limits() -> None:
    """Called in child process (preexec_fn) to apply resource constraints."""
    try:
        # CPU time limit: 60 seconds (belt-and-suspenders alongside timeout=)
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
        # Address space limit: 512 MB
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except ValueError:
        pass  # Some systems don't support all limits


class CommandExecutor:
    def __init__(
        self,
        registry: CommandRegistry,
        process_guard: ProcessGuard,
        sandbox_dir: str,
        max_output_chars: int = 4000,
    ) -> None:
        self._registry = registry
        self._guard = process_guard
        self._sandbox_dir = Path(sandbox_dir).resolve()
        self._sandbox_dir.mkdir(parents=True, exist_ok=True)
        self._max_output_chars = max_output_chars

    async def execute(
        self,
        command: CommandDefinition,
        args: dict[str, str],
        user_id: str,
    ) -> ExecutionResult:
        """Execute a registered script. Never accepts arbitrary paths."""
        import asyncio
        return await asyncio.to_thread(self._execute_sync, command, args, user_id)

    def _execute_sync(
        self,
        command: CommandDefinition,
        args: dict[str, str],
        user_id: str,
    ) -> ExecutionResult:
        script_path = self._registry.resolve_script_path(command)
        if not script_path.exists():
            logger.error("executor.script_not_found", path=str(script_path))
            return ExecutionResult(
                command_name=command.name,
                exit_code=1,
                stdout="",
                stderr="Script not found.",
            )

        # Parameters are passed as JSON on stdin — never as CLI arguments.
        # This prevents shell injection through argument values.
        stdin_payload = json.dumps(
            {
                "user_id": user_id,
                "command": command.name,
                "args": {k: args.get(k, "") for k in command.required_args},
            },
            ensure_ascii=False,
        ).encode("utf-8")

        argv = [str(script_path)]
        env = _safe_env()

        logger.info(
            "executor.run",
            command=command.name,
            user_id=user_id,
            script=str(script_path),
        )

        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=str(self._sandbox_dir),
                start_new_session=True,   # creates new process group for killpg
                preexec_fn=_set_resource_limits,
            )
            self._guard.register(proc.pid, user_id, command.max_runtime_seconds)

            try:
                stdout_b, stderr_b = proc.communicate(
                    input=stdin_payload,
                    timeout=command.max_runtime_seconds,
                )
                timed_out = False
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_b, stderr_b = proc.communicate()
                timed_out = True

            self._guard.unregister(proc.pid)

            stdout = stdout_b.decode("utf-8", errors="replace")[: self._max_output_chars]
            stderr = stderr_b.decode("utf-8", errors="replace")[: self._max_output_chars]

            return ExecutionResult(
                command_name=command.name,
                exit_code=proc.returncode,
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
            )

        except Exception as exc:
            logger.error("executor.exception", command=command.name, error=str(exc))
            return ExecutionResult(
                command_name=command.name,
                exit_code=1,
                stdout="",
                stderr=str(exc),
            )
