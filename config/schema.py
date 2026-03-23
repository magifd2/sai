"""Configuration schema for SAI.

All settings can be provided via:
  1. sai.toml config file
  2. Environment variables with SAI_ prefix (override config file)
  3. CLI flags (override both)

Environment variable naming convention:
  SAI_<SECTION>_<KEY>  e.g. SAI_LLM_BASE_URL, SAI_SLACK_BOT_TOKEN
"""

from pydantic import BaseModel, Field


class SlackConfig(BaseModel):
    bot_token: str = Field(description="Slack bot token (xoxb-...)")
    app_token: str = Field(description="Slack app-level token for Socket Mode (xapp-...)")
    workspace_name: str = Field(default="workspace", description="Display name for this workspace")
    response_language: str = Field(
        default="",
        description=(
            "Language for bot responses (e.g. 'Japanese', 'English'). "
            "Leave empty to auto-detect from each user message."
        ),
    )


class LLMConfig(BaseModel):
    base_url: str = Field(
        default="http://localhost:1234/v1",
        description="OpenAI-compatible API base URL (LM Studio default)",
    )
    api_key: str = Field(default="lm-studio", description="API key for LLM endpoint")
    model: str = Field(default="openai/gpt-oss-20b", description="Chat model name")
    embed_model: str = Field(
        default="text-embedding-nomic-embed-text-v1.5",
        description="Embedding model name",
    )
    embed_dim: int = Field(
        default=768,
        description="Embedding vector dimension (must match the embed_model output size)",
    )
    max_tokens: int = Field(default=4096, description="Max tokens per LLM response")
    temperature: float = Field(default=0.2, description="Sampling temperature")
    timeout_chat: int = Field(default=120, description="Chat request timeout in seconds")
    timeout_embed: int = Field(default=30, description="Embed request timeout in seconds")
    context_window: int = Field(default=120000, description="Model context window size in tokens")
    max_concurrent_requests: int = Field(
        default=4,
        description="Maximum number of concurrent LLM API requests (chat + embed combined)",
    )


class MemoryConfig(BaseModel):
    hot_max_age_hours: int = Field(
        default=24, description="HOT memory expires after this many hours"
    )
    warm_max_age_days: int = Field(
        default=7, description="WARM memory expires after this many days"
    )
    aging_check_interval_minutes: int = Field(
        default=30, description="How often to run the aging scheduler (minutes)"
    )
    archive_check_interval_hours: int = Field(
        default=6, description="How often to run the archive job (hours)"
    )
    max_hot_records_per_user: int = Field(
        default=500, description="Hard cap on HOT records per user before forced aging"
    )
    pin_reactions: list[str] = Field(
        default=["pushpin", "star", "bookmark", "memo"],
        description=(
            "Slack reaction names that trigger persistent pinned memory. "
            "Pinned records are never aged or archived."
        ),
    )


class RagConfig(BaseModel):
    n_results_default: int = Field(default=5, description="Default number of RAG results to retrieve")
    similarity_threshold: float = Field(
        default=0.5, description="Minimum similarity score for RAG results (0-1)"
    )


class SecurityConfig(BaseModel):
    whitelist_mode: bool = Field(
        default=False,
        description="If True, only users in the whitelist can interact with the bot",
    )
    default_whitelist: list[str] = Field(
        default=[],
        description="User IDs pre-populated into the whitelist at startup",
    )
    default_blacklist: list[str] = Field(
        default=[],
        description="User IDs pre-populated into the blacklist at startup",
    )
    rate_limit_per_minute: int = Field(
        default=10, description="Max requests per user per minute"
    )
    rate_limit_per_hour: int = Field(
        default=50, description="Max requests per user per hour"
    )
    max_input_chars: int = Field(
        default=2000, description="Max input length accepted from users"
    )
    injection_block_on_detect: bool = Field(
        default=True,
        description="Block the request if prompt injection is detected (vs. log only)",
    )


class CommandConfig(BaseModel):
    scripts_dir: str = Field(default="./scripts", description="Directory containing command scripts")
    sandbox_dir: str = Field(
        default="./data/sandbox", description="Working directory for script execution"
    )
    max_runtime_seconds: int = Field(
        default=30, description="Maximum script execution time before SIGKILL"
    )
    max_output_chars: int = Field(
        default=4000, description="Maximum characters returned from command output to Slack"
    )


class DatabaseConfig(BaseModel):
    path: str = Field(default="./data/sai.db", description="SQLite database file path")
    wal_mode: bool = Field(
        default=True, description="Enable WAL mode for concurrent read performance"
    )


class SaiConfig(BaseModel):
    slack: SlackConfig
    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    commands: CommandConfig = Field(default_factory=CommandConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    log_level: str = Field(default="INFO", description="Logging level")
    changelog_path: str = Field(default="./CHANGELOG.md")
