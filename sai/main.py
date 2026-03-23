"""SAI entry point: initialize all components and start the Slack Socket Mode listener."""

import asyncio
import signal
from dataclasses import dataclass
from typing import Optional

import click
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from config.loader import load_config
from config.schema import SaiConfig

from .app import Application
from .commands.executor import CommandExecutor
from .commands.registry import CommandRegistry
from .llm.planner import ActionPlanner
from .db import connection_manager, init_schema
from .db.repositories import (
    ACLRepository, ChannelRepository, CommandLogRepository,
    EmbeddingRepository, MemoryRepository, RateLimitRepository, UserRepository,
)
from .llm.client import LLMClient
from .memory.lifecycle import LifecycleManager
from .memory.scheduler import MemoryScheduler
from .memory.summarizer import Summarizer
from .rag.retriever import Retriever
from .security.acl import ACLManager
from .security.ddos import RateLimiter
from .security.process_guard import ProcessGuard
from .slack.cache import CacheManager
from .slack.client import SlackClient
from .slack.events import parse_event
from .utils.logging import get_logger, setup_logging

logger = get_logger(__name__)


@dataclass
class _AppBundle:
    """All wired-up components returned by build_application."""
    app: Application
    scheduler: MemoryScheduler
    acl: ACLManager
    cache: CacheManager
    slack_client: SlackClient
    llm: LLMClient


def build_application(cfg: SaiConfig) -> _AppBundle:
    """Construct and wire all application components from config."""

    # --- DB ---
    connection_manager.initialize(cfg.database.path)
    init_schema(embed_dim=cfg.llm.embed_dim)

    # --- Repositories ---
    memory_repo = MemoryRepository()
    embedding_repo = EmbeddingRepository(embed_dim=cfg.llm.embed_dim)
    user_repo = UserRepository()
    channel_repo = ChannelRepository()
    acl_repo = ACLRepository()
    rate_limit_repo = RateLimitRepository()
    cmd_log_repo = CommandLogRepository()

    # --- Slack ---
    slack_client = SlackClient(cfg.slack.bot_token)
    cache = CacheManager(slack_client, user_repo, channel_repo)

    # --- LLM ---
    llm = LLMClient(
        base_url=cfg.llm.base_url,
        api_key=cfg.llm.api_key,
        model=cfg.llm.model,
        embed_model=cfg.llm.embed_model,
        timeout_chat=cfg.llm.timeout_chat,
        timeout_embed=cfg.llm.timeout_embed,
        max_tokens=cfg.llm.max_tokens,
        temperature=cfg.llm.temperature,
        max_concurrent_requests=cfg.llm.max_concurrent_requests,
    )

    # --- Security ---
    acl = ACLManager(acl_repo, whitelist_mode=cfg.security.whitelist_mode)
    rate_limiter = RateLimiter(
        rate_limit_repo,
        limit_per_minute=cfg.security.rate_limit_per_minute,
        limit_per_hour=cfg.security.rate_limit_per_hour,
    )
    process_guard = ProcessGuard()

    # --- Memory ---
    summarizer = Summarizer(llm, workspace_name=cfg.slack.workspace_name)
    retriever = Retriever(
        llm, embedding_repo, memory_repo,
        n_results=cfg.rag.n_results_default,
        similarity_threshold=cfg.rag.similarity_threshold,
        use_hyde=cfg.rag.use_hyde,
    )
    lifecycle = LifecycleManager(
        memory_repo, embedding_repo, summarizer,
        hot_max_age_hours=cfg.memory.hot_max_age_hours,
        warm_max_age_days=cfg.memory.warm_max_age_days,
    )
    scheduler = MemoryScheduler(
        lifecycle,
        process_guard,
        aging_interval_minutes=cfg.memory.aging_check_interval_minutes,
        archive_interval_hours=cfg.memory.archive_check_interval_hours,
    )

    # --- Commands ---
    cmd_registry = CommandRegistry(cfg.commands.scripts_dir)
    cmd_registry.load()
    planner = ActionPlanner(llm, cmd_registry, cfg.slack.workspace_name)
    cmd_executor = CommandExecutor(
        cmd_registry, process_guard,
        sandbox_dir=cfg.commands.sandbox_dir,
        max_output_chars=cfg.commands.max_output_chars,
    )

    # --- Application ---
    app = Application(
        slack_client=slack_client,
        cache=cache,
        llm=llm,
        acl=acl,
        rate_limiter=rate_limiter,
        retriever=retriever,
        memory_repo=memory_repo,
        embedding_repo=embedding_repo,
        command_log_repo=cmd_log_repo,
        command_registry=cmd_registry,
        planner=planner,
        command_executor=cmd_executor,
        pin_reactions=cfg.memory.pin_reactions,
        max_input_chars=cfg.security.max_input_chars,
        block_on_injection=cfg.security.injection_block_on_detect,
        workspace_name=cfg.slack.workspace_name,
        response_language=cfg.slack.response_language,
    )

    return _AppBundle(
        app=app,
        scheduler=scheduler,
        acl=acl,
        cache=cache,
        slack_client=slack_client,
        llm=llm,
    )


async def run(cfg: SaiConfig) -> None:
    """Async main: start Socket Mode listener and background scheduler."""
    bundle = build_application(cfg)

    # Seed ACL from config (uses the already-constructed ACL manager)
    await bundle.acl.seed_from_config(
        cfg.security.default_whitelist,
        cfg.security.default_blacklist,
    )

    # Warm up caches (uses the already-constructed cache manager)
    await bundle.cache.warm_up()

    # Start memory background scheduler (includes process guard cleanup)
    bundle.scheduler.start()

    # Start Socket Mode (reuse the already-created Slack WebClient)
    socket_client = SocketModeClient(
        app_token=cfg.slack.app_token,
        web_client=bundle.slack_client._client,
    )

    async def _on_event(client: SocketModeClient, req: SocketModeRequest) -> None:
        # ACK immediately to satisfy Slack's 3-second requirement
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        if req.type != "events_api":
            return

        event = parse_event(req.payload)
        if event is None:
            return

        try:
            await bundle.app.handle_event(event)
        except Exception as exc:
            logger.error("app.unhandled_exception", error=str(exc), exc_info=True)

    socket_client.socket_mode_request_listeners.append(_on_event)

    logger.info("sai.starting", workspace=cfg.slack.workspace_name)
    await socket_client.connect()

    # Graceful shutdown on SIGINT / SIGTERM
    stop_event = asyncio.Event()

    def _shutdown(sig: signal.Signals) -> None:
        logger.info("sai.shutdown_signal", signal=sig.name)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    logger.info("sai.ready")
    await stop_event.wait()

    bundle.scheduler.stop()
    await socket_client.disconnect()
    await bundle.llm.aclose()
    connection_manager.close()
    logger.info("sai.stopped")


@click.group()
def cli() -> None:
    """SAI - Slack AI Command Interpreter"""


@cli.command()
@click.option("--config", "config_path", default="sai.toml", help="Config file path")
def start(config_path: str) -> None:
    """Start the SAI bot."""
    cfg = load_config(config_path)
    setup_logging(cfg.log_level)
    asyncio.run(run(cfg))


@cli.command()
@click.option("--db-path", default="./data/sai.db", show_default=True, help="Database file path")
@click.option("--embed-dim", default=768, show_default=True, help="Embedding vector dimension")
def init_db(db_path: str, embed_dim: int) -> None:
    """Initialize the database schema."""
    connection_manager.initialize(db_path)
    init_schema(embed_dim=embed_dim)
    click.echo(f"Database initialized at: {db_path}")


@cli.group()
def memory() -> None:
    """Inspect and monitor memory contents (run while SAI is stopped)."""


def _init_db_only(db_path: str) -> MemoryRepository:
    """Open the database in read-only mode and return a MemoryRepository.

    Read-only mode allows monitoring commands to run while SAI is active.
    """
    connection_manager.initialize(db_path, read_only=True)
    return MemoryRepository()


@memory.command("stats")
@click.option("--db-path", default="./data/sai.db", show_default=True, help="Database file path")
def memory_stats(db_path: str) -> None:
    """Show record counts grouped by memory state."""
    repo = _init_db_only(db_path)

    async def _run() -> None:
        counts = await repo.count_by_state()
        archive = await repo.count_archive()
        states = ["hot", "warm", "cold", "pinned"]
        active_total = sum(counts.get(s, 0) for s in states)

        click.echo(f"{'State':<10} {'Count':>6}")
        click.echo("-" * 18)
        for s in states:
            click.echo(f"{s.upper():<10} {counts.get(s, 0):>6}")
        click.echo("-" * 18)
        click.echo(f"{'ACTIVE':<10} {active_total:>6}")
        click.echo(f"{'ARCHIVE':<10} {archive:>6}")

    asyncio.run(_run())


@memory.command("list")
@click.option("--db-path", default="./data/sai.db", show_default=True, help="Database file path")
@click.option("--state", "state_filter", default=None,
              type=click.Choice(["hot", "warm", "cold", "pinned"], case_sensitive=False),
              help="Filter by state")
@click.option("--user", "user_id", default=None, help="Filter by user ID")
@click.option("--channel", "channel_id", default=None, help="Filter by channel ID")
@click.option("--limit", default=20, show_default=True, help="Max records to show (0 = unlimited)")
def memory_list(db_path: str, state_filter: Optional[str], user_id: Optional[str],
                channel_id: Optional[str], limit: int) -> None:
    """List memory records (newest first)."""
    from .memory.models import MemoryState
    repo = _init_db_only(db_path)

    async def _run() -> None:
        state = MemoryState(state_filter) if state_filter else None
        records = await repo.find_filtered(
            state=state, user_id=user_id, channel_id=channel_id, limit=limit
        )
        if not records:
            click.echo("No records found.")
            return

        click.echo(f"{'ID':<12} {'Created':<20} {'State':<7} {'User':<16} {'Channel':<16} Content")
        click.echo("-" * 110)
        for r in records:
            ts = r.created_at.strftime("%Y-%m-%d %H:%M:%S")
            ch = r.channel_name or r.channel_id
            content_preview = r.content.replace("\n", " ")[:45]
            if len(r.content) > 45:
                content_preview += "…"
            click.echo(f"{r.id[:10]:<12} {ts:<20} {r.state.value:<7} {r.user_name:<16} {ch:<16} {content_preview}")

    asyncio.run(_run())


@memory.command("show")
@click.argument("record_id")
@click.option("--db-path", default="./data/sai.db", show_default=True, help="Database file path")
def memory_show(record_id: str, db_path: str) -> None:
    """Show full details of a single memory record."""
    repo = _init_db_only(db_path)

    async def _run() -> None:
        # Support full ID or unambiguous prefix
        record = await repo.get_by_id(record_id)
        if record is None:
            matches = await repo.find_by_id_prefix(record_id)
            if len(matches) == 1:
                record = matches[0]
            elif len(matches) > 1:
                click.echo(f"Ambiguous prefix '{record_id}' matches {len(matches)} records:", err=True)
                for m in matches:
                    click.echo(f"  {m.id}", err=True)
                raise SystemExit(1)
            else:
                click.echo(f"Record not found: {record_id}", err=True)
                raise SystemExit(1)

        click.echo(f"ID          : {record.id}")
        click.echo(f"State       : {record.state.value}")
        click.echo(f"User        : {record.user_name} ({record.user_id})")
        click.echo(f"Channel     : {record.channel_name or ''} ({record.channel_id})")
        click.echo(f"Created     : {record.created_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        click.echo(f"Is summary  : {record.is_summary}")
        if record.summary_of:
            click.echo(f"Summary of  : {', '.join(record.summary_of)}")
        if record.pinned_at:
            click.echo(f"Pinned at   : {record.pinned_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            click.echo(f"Pinned by   : {record.pinned_by}")
            click.echo(f"Reaction    : {record.pin_reaction}")
        click.echo(f"Embedding   : {record.embedding_id or '(none)'}")
        click.echo("")
        click.echo("Content:")
        click.echo("-" * 60)
        click.echo(record.content)

    asyncio.run(_run())


@cli.command()
@click.option("--config", "config_path", default="sai.toml", help="Config file path")
def check(config_path: str) -> None:
    """Check configuration and LLM connectivity."""
    cfg = load_config(config_path)
    setup_logging(cfg.log_level)

    async def _check() -> None:
        llm = LLMClient(
            base_url=cfg.llm.base_url,
            api_key=cfg.llm.api_key,
            model=cfg.llm.model,
            embed_model=cfg.llm.embed_model,
        )
        try:
            ok = await llm.health_check()
            status = "reachable" if ok else "unreachable"
            click.echo(f"LLM endpoint ({cfg.llm.base_url}): {status}")
        finally:
            await llm.aclose()

    asyncio.run(_check())
