"""Command registry: load and store command definitions from scripts directory."""

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from ..utils.logging import get_logger

logger = get_logger(__name__)

_MANIFEST_FILE = "commands.json"


class CommandDefinition(BaseModel):
    name: str
    description: str          # natural language description shown in the menu
    script_path: str          # relative to scripts_dir
    required_args: list[str] = []
    max_runtime_seconds: int = 30
    allowed_users: list[str] = []  # empty = all whitelisted users


class CommandRegistry:
    def __init__(self, scripts_dir: str) -> None:
        self._scripts_dir = Path(scripts_dir).resolve()
        self._commands: list[CommandDefinition] = []

    def load(self) -> None:
        """Load command definitions from {scripts_dir}/commands.json."""
        manifest = self._scripts_dir / _MANIFEST_FILE
        if not manifest.exists():
            logger.warning("command_registry.no_manifest", path=str(manifest))
            return

        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self._commands = [CommandDefinition(**item) for item in data]
            logger.info("command_registry.loaded", count=len(self._commands))
        except Exception as exc:
            logger.error("command_registry.load_failed", error=str(exc))

    @property
    def commands(self) -> list[CommandDefinition]:
        return list(self._commands)

    @property
    def menu(self) -> list[str]:
        """Return natural language descriptions for the command selection prompt."""
        return [cmd.description for cmd in self._commands]

    def get_by_index(self, index: int) -> Optional[CommandDefinition]:
        """1-based index (as returned by LLM command selection)."""
        if 1 <= index <= len(self._commands):
            return self._commands[index - 1]
        return None

    def get_by_name(self, name: str) -> Optional[CommandDefinition]:
        for cmd in self._commands:
            if cmd.name == name:
                return cmd
        return None

    def resolve_script_path(self, cmd: CommandDefinition) -> Path:
        return self._scripts_dir / cmd.script_path
