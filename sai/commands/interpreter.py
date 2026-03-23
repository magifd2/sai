"""Natural language → command mapper via LLM."""

import json
from dataclasses import dataclass, field
from typing import Optional

from ..llm.client import LLMClient
from ..llm import nonce as nonce_mod, prompts
from ..llm.response_parser import parse_command_index
from ..utils.logging import get_logger
from .registry import CommandDefinition, CommandRegistry

logger = get_logger(__name__)


@dataclass
class CommandMatch:
    command: CommandDefinition
    args: dict[str, str] = field(default_factory=dict)


class CommandInterpreter:
    def __init__(
        self,
        llm: LLMClient,
        registry: CommandRegistry,
        workspace_name: str = "workspace",
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._workspace_name = workspace_name

    async def interpret(
        self, user_text: str
    ) -> Optional[CommandMatch]:
        """
        Map user_text to a registered command.
        Returns None if no command matches.

        Security: LLM output is parsed as a strict integer.
        The LLM cannot inject arbitrary script paths.
        """
        menu = self._registry.menu
        if not menu:
            return None

        # Step 1: command selection
        request_nonce = nonce_mod.generate()
        messages = prompts.build_command_select_prompt(
            user_text=user_text,
            command_menu=menu,
            request_nonce=request_nonce,
            workspace_name=self._workspace_name,
        )

        # Low temperature for deterministic selection
        raw_response = await self._llm.chat(
            messages,
            max_tokens=10,
            temperature=0.0,
            nonce=request_nonce,
        )

        idx = parse_command_index(raw_response.strip(), max_index=len(menu))
        if idx is None:
            logger.debug("interpreter.no_match", snippet=user_text[:50])
            return None

        command = self._registry.get_by_index(idx)
        if command is None:
            return None

        # Step 2: argument extraction (if needed)
        args: dict[str, str] = {}
        if command.required_args:
            args = await self._extract_args(user_text, command)

        logger.info(
            "interpreter.matched",
            command=command.name,
            args=list(args.keys()),
        )
        return CommandMatch(command=command, args=args)

    async def _extract_args(
        self, user_text: str, command: CommandDefinition
    ) -> dict[str, str]:
        request_nonce = nonce_mod.generate()
        messages = prompts.build_arg_extract_prompt(
            user_text=user_text,
            command_name=command.name,
            required_args=command.required_args,
            request_nonce=request_nonce,
            workspace_name=self._workspace_name,
        )
        raw = await self._llm.chat(
            messages,
            max_tokens=256,
            temperature=0.0,
            nonce=request_nonce,
        )
        try:
            parsed = json.loads(raw.strip())
            if isinstance(parsed, dict):
                return {k: str(v) for k, v in parsed.items() if v is not None}
        except (json.JSONDecodeError, ValueError):
            logger.warning("interpreter.arg_parse_failed", raw=raw[:100])
        return {}
