"""Natural language → command mapper via LLM."""

from dataclasses import dataclass, field
from typing import Optional

from ..llm.client import ChatMessage, LLMClient
from ..llm import nonce as nonce_mod, prompts
from ..llm.output_parser import extract_int, extract_json, is_empty, retry_structured
from ..utils.logging import get_logger
from .registry import CommandDefinition, CommandRegistry

logger = get_logger(__name__)

_MAX_SELECT_ATTEMPTS = 3
_MAX_ARG_ATTEMPTS = 3


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
        max_select_attempts: int = _MAX_SELECT_ATTEMPTS,
        max_arg_attempts: int = _MAX_ARG_ATTEMPTS,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._workspace_name = workspace_name
        self._max_select_attempts = max_select_attempts
        self._max_arg_attempts = max_arg_attempts

    async def interpret(self, user_text: str) -> Optional[CommandMatch]:
        """
        Map user_text to a registered command.
        Returns None if no command matches.

        Security: LLM output is parsed as a strict integer via extract_int().
        The LLM cannot inject arbitrary script paths.
        """
        menu = self._registry.menu
        if not menu:
            return None

        idx = await self._select_command(user_text, menu)
        if idx is None:
            logger.debug("interpreter.no_match", snippet=user_text[:50])
            return None

        command = self._registry.get_by_index(idx)
        if command is None:
            return None

        args: dict[str, str] = {}
        if command.required_args:
            args = await self._extract_args(user_text, command)

        logger.info("interpreter.matched", command=command.name, args=list(args.keys()))
        return CommandMatch(command=command, args=args)

    # ------------------------------------------------------------------
    # Command selection with retry
    # ------------------------------------------------------------------

    async def _select_command(
        self, user_text: str, menu: list[str]
    ) -> Optional[int]:
        """
        Ask the LLM to select a command number.
        Retries with a correction prompt if the response is unparseable
        or contains explanatory prose instead of a bare integer.
        """
        request_nonce = nonce_mod.generate()
        messages = prompts.build_command_select_prompt(
            user_text=user_text,
            command_menu=menu,
            request_nonce=request_nonce,
            workspace_name=self._workspace_name,
        )

        async def _call() -> str:
            return await self._llm.chat(
                messages,
                max_tokens=50,
                temperature=0.1,
                nonce=request_nonce,
            )

        async def _correction(bad_response: str) -> str:
            correction_messages = messages + [
                ChatMessage(role="assistant", content=bad_response),
                ChatMessage(
                    role="user",
                    content=(
                        "Your response was not a valid number. "
                        "Reply with ONLY a single integer (e.g. '2') "
                        "or ONLY the word 'none'. No other text."
                    ),
                ),
            ]
            return await self._llm.chat(
                correction_messages,
                max_tokens=10,
                temperature=0.0,
                nonce=request_nonce,
            )

        return await retry_structured(
            call_fn=_call,
            parse_fn=lambda raw: extract_int(raw, max_value=len(menu)),
            correction_call_fn=_correction,
            max_attempts=self._max_select_attempts,
            label="command_select",
        )

    # ------------------------------------------------------------------
    # Argument extraction with retry
    # ------------------------------------------------------------------

    async def _extract_args(
        self, user_text: str, command: CommandDefinition
    ) -> dict[str, str]:
        """
        Ask the LLM to extract structured arguments as a JSON object.
        Uses robust JSON extraction (handles code fences, prose prefix, trailing
        commas) and retries with a correction prompt if parsing fails.
        """
        request_nonce = nonce_mod.generate()
        messages = prompts.build_arg_extract_prompt(
            user_text=user_text,
            command_name=command.name,
            required_args=command.required_args,
            request_nonce=request_nonce,
            workspace_name=self._workspace_name,
        )

        async def _call() -> str:
            return await self._llm.chat(
                messages,
                max_tokens=512,
                temperature=0.0,
                nonce=request_nonce,
            )

        async def _correction(bad_response: str) -> str:
            correction_messages = messages + [
                ChatMessage(role="assistant", content=bad_response),
                ChatMessage(
                    role="user",
                    content=(
                        "Your response could not be parsed as JSON. "
                        "Reply with ONLY a valid JSON object mapping argument names to values. "
                        "Example: {\"arg1\": \"value1\", \"arg2\": \"value2\"}. "
                        "No markdown, no code blocks, no explanation."
                    ),
                ),
            ]
            return await self._llm.chat(
                correction_messages,
                max_tokens=512,
                temperature=0.0,
                nonce=request_nonce,
            )

        def _parse(raw: str) -> Optional[dict[str, str]]:
            if is_empty(raw):
                return None
            parsed = extract_json(raw)
            if isinstance(parsed, dict):
                return {k: str(v) for k, v in parsed.items() if v is not None}
            return None

        result = await retry_structured(
            call_fn=_call,
            parse_fn=_parse,
            correction_call_fn=_correction,
            max_attempts=self._max_arg_attempts,
            label=f"arg_extract:{command.name}",
        )
        return result or {}
