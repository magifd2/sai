"""ActionPlanner: understand user intent then decide how to respond.

Single LLM call that produces a structured ActionPlan containing:
  - intent   : plain-language description of what the user wants
  - action   : "command" | "rag" | "none"
  - command_index : 1-based command number (action=command only)
  - args     : extracted arguments (action=command only)
  - rag_query: optimised search query  (action=rag only)

Replaces the previous two-step approach of:
  1. CommandInterpreter (command selection + arg extraction, separate LLM calls)
  2. Hard-coded RAG fallback
"""

from typing import Optional

from pydantic import BaseModel

from ..commands.registry import CommandRegistry
from ..utils.logging import get_logger
from . import nonce as nonce_mod
from .client import ChatMessage, LLMClient
from .output_parser import extract_json, retry_structured

logger = get_logger(__name__)


class ActionPlan(BaseModel):
    """Parsed result from the planner LLM call."""
    intent: str                            # what the user wants (for logging / context)
    action: str                            # "command" | "rag" | "summarize_channel" | "summarize_thread" | "none"
    command_index: Optional[int] = None    # 1-based; only when action="command"
    args: dict[str, str] = {}              # extracted args; only when action="command"
    rag_query: Optional[str] = None        # refined query; only when action="rag"


class ActionPlanner:
    """Hierarchical intent → action planner backed by an LLM."""

    _VALID_ACTIONS = {"command", "rag", "summarize_channel", "summarize_thread", "none"}

    def __init__(
        self,
        llm: LLMClient,
        registry: CommandRegistry,
        workspace_name: str = "workspace",
        max_attempts: int = 3,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._workspace_name = workspace_name
        self._max_attempts = max_attempts

    async def plan(
        self,
        user_text: str,
        current_datetime: Optional[str] = None,
    ) -> ActionPlan:
        """
        Analyse user_text and return an ActionPlan.
        Falls back to ActionPlan(action="rag") if the LLM fails to produce
        valid JSON after max_attempts — ensures the caller always gets a plan.
        """
        nonce = nonce_mod.generate()
        messages = self._build_messages(user_text, nonce, current_datetime)
        n_commands = len(self._registry.commands)

        async def _call() -> str:
            return await self._llm.chat(
                messages,
                max_tokens=400,
                temperature=0.1,
                nonce=nonce,
            )

        async def _correction(bad: str) -> str:
            follow_up = messages + [
                ChatMessage(role="assistant", content=bad),
                ChatMessage(
                    role="user",
                    content=(
                        "Your response was not valid JSON. "
                        "Reply with ONLY the JSON object. No markdown, no explanation."
                    ),
                ),
            ]
            return await self._llm.chat(
                follow_up,
                max_tokens=400,
                temperature=0.1,
                nonce=nonce,
            )

        def _parse(raw: str) -> Optional[ActionPlan]:
            data = extract_json(raw)
            if not isinstance(data, dict):
                return None
            try:
                plan = ActionPlan.model_validate(data)
            except Exception as exc:
                logger.warning("planner.validation_error", error=str(exc))
                return None

            if plan.action not in self._VALID_ACTIONS:
                logger.warning("planner.invalid_action", action=plan.action)
                return None

            if plan.action == "command":
                if plan.command_index is None or not (1 <= plan.command_index <= n_commands):
                    logger.warning("planner.invalid_command_index", index=plan.command_index)
                    return None

            return plan

        result = await retry_structured(
            call_fn=_call,
            parse_fn=_parse,
            correction_call_fn=_correction,
            max_attempts=self._max_attempts,
            label="action_plan",
        )

        if result is None:
            logger.warning("planner.fallback_to_rag", snippet=user_text[:60])
            return ActionPlan(intent=user_text, action="rag", rag_query=user_text)

        logger.info(
            "planner.plan",
            intent=result.intent,
            action=result.action,
            command_index=result.command_index,
        )
        return result

    # ------------------------------------------------------------------

    def _build_messages(
        self,
        user_text: str,
        nonce: str,
        current_datetime: Optional[str],
    ) -> list[ChatMessage]:
        datetime_line = f"Current date/time: {current_datetime}\n" if current_datetime else ""

        commands = self._registry.commands
        if commands:
            cmd_lines: list[str] = []
            for i, cmd in enumerate(commands, 1):
                arg_info = f"  required args: {cmd.required_args}" if cmd.required_args else "  args: none"
                cmd_lines.append(f"{i}. {cmd.description}\n{arg_info}")
            cmd_block = "\n".join(cmd_lines)
        else:
            cmd_block = "(no commands registered)"

        system = (
            f"You are SAI's intent analyzer for the {self._workspace_name} Slack workspace.\n"
            f"{datetime_line}"
            "\nYour job is to:\n"
            "  Step 1 — Understand what the user wants (write a concise intent statement).\n"
            "  Step 2 — Choose the best action:\n"
            '    "command"          : a registered command can fulfil the request\n'
            '    "rag"              : search past Slack messages to answer the question\n'
            '    "summarize_channel": user wants a summary of what happened in this channel\n'
            '    "summarize_thread" : user wants a summary of the current thread conversation\n'
            '    "none"             : the request is outside all capabilities\n'
            "\nRegistered commands:\n"
            f"{cmd_block}\n"
            "\nReply with ONLY this JSON object (no markdown, no extra text):\n"
            "{\n"
            '  "intent": "<one sentence describing what the user wants>",\n'
            '  "action": "command" | "rag" | "summarize_channel" | "summarize_thread" | "none",\n'
            '  "command_index": <1-based integer, omit if action != "command">,\n'
            '  "args": {"<arg>": "<value>", ...},\n'
            '  "rag_query": "<search-optimised query, omit if action != \\"rag\\">"\n'
            "}"
        )

        wrapped_user = nonce_mod.wrap(user_text, nonce, role="user-request")
        return [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=wrapped_user),
        ]
