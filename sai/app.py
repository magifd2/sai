"""Application orchestrator.

Wires all components together and defines the event processing pipeline.

Processing order (security rules — never reorder):
  1. Parse event
  2. ACL check          ← first always
  3. Rate limit check   ← second always
  4. Sanitize input
  5. Dispatch:
     - MESSAGE events   → store in HOT memory + index embedding
     - APP_MENTION      → RAG retrieval + LLM answer (or command execution)
     - REACTION_ADDED   → pin memory if reaction is in pin_reactions list
"""

import time
from collections import OrderedDict
from typing import Optional

from .commands.executor import CommandExecutor
from .commands.registry import CommandRegistry
from .db.repositories.memory import MemoryRepository
from .db.repositories.embedding import EmbeddingRepository
from .db.repositories.command_log import CommandLogRepository
from .llm import nonce as nonce_mod, prompts
from .llm.client import LLMClient
from .llm.planner import ActionPlanner
from .llm.sanitizer import sanitize
from .memory.models import MemoryRecord, MemoryState
from .rag.retriever import Retriever
from .security.acl import ACLManager
from .security.ddos import RateLimiter
from .slack.cache import CacheManager
from .slack.client import SlackClient
from .slack.events import SlackEvent, SlackEventType
from .slack.markdown import md_to_slack_blocks, split_blocks_for_slack
from .utils.ids import new_id
from .utils.logging import get_logger
from .utils.time import utcnow

logger = get_logger(__name__)


class Application:
    def __init__(
        self,
        slack_client: SlackClient,
        cache: CacheManager,
        llm: LLMClient,
        acl: ACLManager,
        rate_limiter: RateLimiter,
        retriever: Retriever,
        memory_repo: MemoryRepository,
        embedding_repo: EmbeddingRepository,
        command_log_repo: CommandLogRepository,
        command_registry: CommandRegistry,
        planner: ActionPlanner,
        command_executor: CommandExecutor,
        pin_reactions: list[str],
        max_input_chars: int = 2000,
        block_on_injection: bool = True,
        workspace_name: str = "workspace",
        response_language: str = "",
    ) -> None:
        self._slack = slack_client
        self._cache = cache
        self._llm = llm
        self._acl = acl
        self._rate_limiter = rate_limiter
        self._retriever = retriever
        self._memory = memory_repo
        self._embeddings = embedding_repo
        self._cmd_log = command_log_repo
        self._cmd_registry = command_registry
        self._planner = planner
        self._cmd_executor = command_executor
        self._pin_reactions = set(pin_reactions)
        self._max_input_chars = max_input_chars
        self._block_on_injection = block_on_injection
        self._workspace_name = workspace_name
        self._response_language = response_language
        # Dedup cache: protects against Slack SDK re-delivering events on reconnect.
        # Keys are "ts#channel_id"; values are the monotonic time of first processing.
        self._seen_events: OrderedDict[str, float] = OrderedDict()
        self._seen_events_ttl: float = 300.0  # 5 minutes

    def _is_duplicate_event(self, event: SlackEvent) -> bool:
        """Return True if this event has already been processed (dedup guard).

        Slack Socket Mode may re-deliver events on reconnection. We track
        recent (ts, channel_id) pairs and discard any repeat within the TTL.
        """
        key = f"{event.ts}#{event.channel_id}"
        now = time.monotonic()

        if key in self._seen_events:
            logger.warning(
                "app.duplicate_event_dropped",
                ts=event.ts,
                channel_id=event.channel_id,
                event_type=event.event_type.value,
            )
            return True

        self._seen_events[key] = now

        # Evict entries older than TTL (OrderedDict is insertion-ordered)
        cutoff = now - self._seen_events_ttl
        while self._seen_events:
            oldest_key, oldest_time = next(iter(self._seen_events.items()))
            if oldest_time < cutoff:
                self._seen_events.popitem(last=False)
            else:
                break

        return False

    async def handle_event(self, event: SlackEvent) -> None:
        """Main event dispatch — entry point for all Slack events."""

        # ── 0. Dedup guard (re-delivered events on SDK reconnect) ─────
        if self._is_duplicate_event(event):
            return

        # ── 1. Resolve user metadata ──────────────────────────────────
        user = await self._cache.get_user(event.user_id)
        is_bot = user.is_bot if user else event.is_bot

        # ── 2. ACL check ─────────────────────────────────────────────
        acl_result = await self._acl.check(event.user_id, is_bot=is_bot)
        if not acl_result.allowed:
            logger.debug("app.acl_denied", user_id=event.user_id, reason=acl_result.reason)
            return

        # ── 3. Rate limit check ───────────────────────────────────────
        rl_result = await self._rate_limiter.check_and_increment(event.user_id)
        if not rl_result.allowed:
            if event.event_type == SlackEventType.APP_MENTION:
                await self._slack.post_message(
                    channel=event.channel_id,
                    text=":hourglass: Too many requests. Please slow down.",
                    thread_ts=event.thread_ts or event.ts,
                )
            return

        # ── 4. Dispatch by event type ────────────────────────────────
        if event.event_type == SlackEventType.MESSAGE:
            # Thread reply: if the parent message is already in memory,
            # treat the reply as a mention to continue the conversation.
            if (
                event.thread_ts
                and event.thread_ts != event.ts
                and await self._memory.get_by_ts(event.thread_ts, event.channel_id)
            ):
                await self._handle_mention(event, user)
            else:
                await self._handle_message(event, user)

        elif event.event_type == SlackEventType.APP_MENTION:
            await self._handle_mention(event, user)

        elif event.event_type == SlackEventType.REACTION_ADDED:
            await self._handle_reaction(event)

    # ------------------------------------------------------------------
    # Message: store in HOT memory and index
    # ------------------------------------------------------------------

    async def _handle_message(self, event: SlackEvent, user) -> None:
        if not event.text.strip():
            return

        channel = await self._cache.get_channel(event.channel_id)
        channel_name = channel.channel_name if channel else None
        user_name = user.user_name if user else event.user_id

        record = MemoryRecord(
            id=new_id(),
            user_id=event.user_id,
            user_name=user_name,
            channel_id=event.channel_id,
            channel_name=channel_name,
            ts=event.ts,
            created_at=event.received_at,
            content=event.text,
            state=MemoryState.HOT,
        )
        await self._memory.save(record)

        # Index embedding asynchronously (best-effort)
        try:
            await self._retriever.index(record)
        except Exception as exc:
            logger.warning("app.index_failed", record_id=record.id, error=str(exc))

    # ------------------------------------------------------------------
    # Mention: sanitize → RAG → LLM answer or command execution
    # ------------------------------------------------------------------

    async def _handle_mention(self, event: SlackEvent, user) -> None:
        # Also store the mention itself in memory
        await self._handle_message(event, user)

        # ── 4a. Sanitize ─────────────────────────────────────────────
        sanitized = sanitize(
            event.text,
            max_chars=self._max_input_chars,
            block_on_injection=self._block_on_injection,
        )
        if sanitized.blocked:
            logger.warning(
                "app.mention_blocked",
                user_id=event.user_id,
                warnings=sanitized.warnings,
            )
            await self._slack.post_message(
                channel=event.channel_id,
                text=":no_entry: Your message was blocked by security filters.",
                thread_ts=event.thread_ts or event.ts,
            )
            return

        clean_text = sanitized.clean
        now = utcnow().astimezone()
        current_datetime = now.strftime("%Y-%m-%d %H:%M:%S %Z")

        # ── 4b. Hierarchical intent analysis + action planning ────────
        plan = await self._planner.plan(clean_text, current_datetime=current_datetime)

        if plan.action == "command":
            command = self._cmd_registry.get_by_index(plan.command_index)
            if command:
                from .commands.interpreter import CommandMatch
                match = CommandMatch(command=command, args=plan.args)
                await self._handle_command(event, match, clean_text)
                return
            # Command index resolved to nothing — fall through to RAG
            logger.warning("app.plan_command_not_found", index=plan.command_index)

        # ── 4c. RAG answer (for "rag" or "none" or fallback) ─────────
        await self._handle_rag_answer(
            event,
            plan.rag_query or clean_text,
            current_datetime=current_datetime,
        )

    async def _handle_command(self, event: SlackEvent, match, clean_text: str) -> None:
        # Check per-command user allowlist
        if match.command.allowed_users and event.user_id not in match.command.allowed_users:
            await self._slack.post_message(
                channel=event.channel_id,
                text=":lock: You don't have permission to run that command.",
                thread_ts=event.thread_ts or event.ts,
            )
            return

        request_nonce = nonce_mod.generate()
        result = await self._cmd_executor.execute(
            command=match.command,
            args=match.args,
            user_id=event.user_id,
        )

        # Audit log
        await self._cmd_log.log(
            user_id=event.user_id,
            channel_id=event.channel_id,
            nl_input=clean_text,
            nonce=request_nonce,
            matched_command=match.command.name,
            script_path=match.command.script_path,
            exit_code=result.exit_code,
            stdout_snippet=result.stdout[:500],
            stderr_snippet=result.stderr[:500],
        )

        resp_data = await self._slack.post_message(
            channel=event.channel_id,
            text=result.format_for_slack(),
            thread_ts=event.thread_ts or event.ts,
        )
        bot_ts = resp_data.get("ts") if resp_data else None
        if bot_ts:
            channel = await self._cache.get_channel(event.channel_id)
            await self._store_bot_response(
                text=result.format_for_slack(),
                channel_id=event.channel_id,
                ts=bot_ts,
                channel_name=channel.channel_name if channel else None,
            )

    async def _handle_rag_answer(
        self,
        event: SlackEvent,
        clean_text: str,
        current_datetime: Optional[str] = None,
    ) -> None:
        # Retrieve relevant memories
        context_records = await self._retriever.retrieve(clean_text)
        # Include speaker identity so the LLM knows who said what
        context_snippets = [
            f"[{r.user_name} ({r.user_id})]: {r.content}"
            for r in context_records
        ]

        request_nonce = nonce_mod.generate()
        if current_datetime is None:
            current_datetime = utcnow().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

        # Resolve requester display info
        requester_user = await self._cache.get_user(event.user_id)
        requester_name = requester_user.user_name if requester_user else event.user_id
        requester = f"{requester_name} ({event.user_id})"

        messages = prompts.build_rag_answer_prompt(
            user_text=clean_text,
            context_snippets=context_snippets,
            request_nonce=request_nonce,
            workspace_name=self._workspace_name,
            current_datetime=current_datetime,
            available_commands=self._cmd_registry.menu or None,
            response_language=self._response_language,
            requester=requester,
        )

        try:
            answer = await self._llm.chat(messages, nonce=request_nonce)
        except Exception as exc:
            logger.error("app.llm_error", error=str(exc))
            await self._slack.post_message(
                channel=event.channel_id,
                text=":warning: I encountered an error. Please try again.",
                thread_ts=event.thread_ts or event.ts,
            )
            return

        blocks = md_to_slack_blocks(answer)
        partitions = split_blocks_for_slack(blocks)
        logger.debug("app.rag_blocks", block_count=len(blocks), partitions=len(partitions))

        if not partitions:
            resp_data = await self._slack.post_message(
                channel=event.channel_id,
                text=answer,
                thread_ts=event.thread_ts or event.ts,
            )
            if resp_data and resp_data.get("ts"):
                channel = await self._cache.get_channel(event.channel_id)
                await self._store_bot_response(
                    text=answer,
                    channel_id=event.channel_id,
                    ts=resp_data["ts"],
                    channel_name=channel.channel_name if channel else None,
                )
            return

        # First partition carries the plain-text fallback for notifications.
        # Subsequent partitions (continuation posts in the same thread) use a
        # blank fallback so only the blocks are visible.
        first_ts: str | None = None
        for idx, partition in enumerate(partitions):
            resp_data = await self._slack.post_message(
                channel=event.channel_id,
                text=answer if idx == 0 else "\u200b",  # zero-width space for continuations
                blocks=partition,
                thread_ts=event.thread_ts or event.ts,
            )
            if idx == 0 and resp_data:
                first_ts = resp_data.get("ts")

        if first_ts:
            channel = await self._cache.get_channel(event.channel_id)
            await self._store_bot_response(
                text=answer,
                channel_id=event.channel_id,
                ts=first_ts,
                channel_name=channel.channel_name if channel else None,
            )

    # ------------------------------------------------------------------
    # Store bot response in HOT memory so it appears in RAG context
    # ------------------------------------------------------------------

    async def _store_bot_response(
        self,
        text: str,
        channel_id: str,
        ts: str,
        channel_name: str | None = None,
    ) -> None:
        """Store a bot-generated response in HOT memory and index it."""
        record = MemoryRecord(
            id=new_id(),
            user_id="SAI",
            user_name="SAI",
            channel_id=channel_id,
            channel_name=channel_name,
            ts=ts,
            created_at=utcnow(),
            content=text,
            state=MemoryState.HOT,
        )
        await self._memory.save(record)
        try:
            await self._retriever.index(record)
        except Exception as exc:
            logger.warning("app.bot_response_index_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Reaction: pin memory if reaction is in pin_reactions list
    # ------------------------------------------------------------------

    async def _handle_reaction(self, event: SlackEvent) -> None:
        reaction = event.reaction
        if reaction not in self._pin_reactions:
            return

        target_ts = event.reaction_target_ts
        target_channel = event.reaction_target_channel or event.channel_id
        if not target_ts:
            return

        # Find the memory record for this message
        record = await self._memory.get_by_ts(target_ts, target_channel)

        if record is None:
            # Message not yet in memory — fetch from Slack and store
            slack_msg = await self._slack.get_message(target_channel, target_ts)
            if slack_msg:
                msg_user_id = slack_msg.get("user", "")
                msg_user = await self._cache.get_user(msg_user_id)
                channel = await self._cache.get_channel(target_channel)
                record = MemoryRecord(
                    id=new_id(),
                    user_id=msg_user_id,
                    user_name=msg_user.user_name if msg_user else msg_user_id,
                    channel_id=target_channel,
                    channel_name=channel.channel_name if channel else None,
                    ts=target_ts,
                    created_at=utcnow(),
                    content=slack_msg.get("text", ""),
                    state=MemoryState.PINNED,
                    pinned_at=utcnow(),
                    pinned_by=event.user_id,
                    pin_reaction=reaction,
                )
                await self._memory.save(record)
                try:
                    await self._retriever.index(record)
                except Exception as exc:
                    logger.warning("app.pin_index_failed", error=str(exc))
                logger.info(
                    "app.pinned_new",
                    ts=target_ts,
                    channel=target_channel,
                    reaction=reaction,
                    pinned_by=event.user_id,
                )
            return

        # Already in memory — transition to PINNED if not already
        if record.state != MemoryState.PINNED:
            await self._memory.pin(
                record_id=record.id,
                pinned_by=event.user_id,
                pin_reaction=reaction,
                pinned_at=utcnow(),
            )
            logger.info(
                "app.pinned_existing",
                record_id=record.id,
                previous_state=record.state,
                reaction=reaction,
                pinned_by=event.user_id,
            )
