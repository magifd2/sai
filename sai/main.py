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
from .commands.interpreter import CommandInterpreter
from .commands.registry import CommandRegistry
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
    embedding_repo = EmbeddingRepository()
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
    cmd_interpreter = CommandInterpreter(llm, cmd_registry, cfg.slack.workspace_name)
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
        command_interpreter=cmd_interpreter,
        command_executor=cmd_executor,
        pin_reactions=cfg.memory.pin_reactions,
        max_input_chars=cfg.security.max_input_chars,
        block_on_injection=cfg.security.injection_block_on_detect,
        workspace_name=cfg.slack.workspace_name,
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
