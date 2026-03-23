# SAI — Slack AI Command Interpreter

A context-aware Slack bot with RAG-based memory, forgetting lifecycle, and natural language command execution.

## Features

- **Real-time memory** — monitors all messages in joined channels via WebSocket (Socket Mode)
- **Smart forgetting** — HOT (full detail) → WARM (LLM summary) → COLD → ARCHIVE lifecycle
- **Pinned memory** — add a configured reaction (e.g. `:pushpin:`) to any post to make it permanently remembered
- **RAG answers** — @mention the bot to get answers grounded in conversation history
- **Command interpreter** — describe what you want in natural language; the bot executes pre-registered scripts
- **Security-first** — ACL (whitelist/blacklist), rate limiting, prompt injection defense, nonce XML encapsulation
- **Local LLM** — uses LM Studio (or any OpenAI-compatible endpoint)

## Requirements

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- [LM Studio](https://lmstudio.ai/) running locally (or any OpenAI-compatible API)
- Slack app with Socket Mode enabled

## Quick Start

```bash
# 1. Install dependencies
uv sync

# 2. Copy and fill in your credentials
cp .env.example .env
# Edit .env with your SAI_SLACK_BOT_TOKEN and SAI_SLACK_APP_TOKEN

# 3. Initialize the database
uv run sai init-db

# 4. Check LLM connectivity
uv run sai check

# 5. Start the bot
uv run sai start
```

## Configuration

Configuration is loaded from `sai.toml` (optional) and `SAI_*` environment variables.
Environment variables take precedence over the config file.

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `SAI_SLACK_BOT_TOKEN` | *(required)* | Slack bot token (`xoxb-...`) |
| `SAI_SLACK_APP_TOKEN` | *(required)* | Slack app token for Socket Mode (`xapp-...`) |
| `SAI_LLM_BASE_URL` | `http://localhost:1234/v1` | LM Studio endpoint |
| `SAI_LLM_API_KEY` | `lm-studio` | LLM API key |
| `SAI_LLM_MODEL` | `openai/gpt-oss-20b` | Chat model |
| `SAI_LLM_EMBED_MODEL` | `text-embedding-nomic-embed-text-v1.5` | Embedding model |
| `SAI_LLM_MAX_CONCURRENT_REQUESTS` | `4` | Max parallel LLM requests |
| `SAI_LOG_LEVEL` | `INFO` | Log level |

See `.env.example` for a full list.

## Memory Lifecycle

```
HOT     (< 24h)    full original message text
  ↓
WARM    (1-7 days) LLM-summarized batch per user/channel
  ↓
COLD    (> 7 days) marked for archival
  ↓
ARCHIVE             moved to archive table, removed from active memory

PINNED              reaction-triggered, never ages, never archived
```

To pin a message permanently, add one of these reactions: 📌 ⭐ 🔖 📝
(configurable via `SAI_MEMORY_PIN_REACTIONS`)

## Adding Commands

1. Create a shell script in `scripts/` that reads parameters from stdin JSON:

```bash
#!/usr/bin/env bash
params=$(cat)
my_arg=$(echo "$params" | python3 -c "import json,sys; print(json.load(sys.stdin)['args']['my_arg'])")
echo "Result: $my_arg"
```

2. Register it in `scripts/commands.json`:

```json
{
  "name": "my_command",
  "description": "Natural language description for the LLM menu",
  "script_path": "my_command.sh",
  "required_args": ["my_arg"],
  "max_runtime_seconds": 30
}
```

## Running Tests

```bash
uv run pytest
uv run pytest --cov=sai --cov-report=term-missing
```

## Project Structure

```
sai/
├── config/          # Configuration schema and loader
├── sai/
│   ├── app.py       # Application orchestrator (event pipeline)
│   ├── db/          # DuckDB + VSS repository layer
│   ├── llm/         # LLM client, prompts, nonce, sanitizer
│   ├── memory/      # Memory models, lifecycle, scheduler
│   ├── rag/         # Embedding + retrieval
│   ├── security/    # ACL, rate limiter, injection detection
│   ├── slack/       # Socket Mode, event parser, cache
│   ├── commands/    # Registry, interpreter, executor
│   └── utils/       # Logging, time, IDs
├── scripts/         # Command scripts + commands.json manifest
├── tests/           # Unit and integration tests
└── docs/            # Architecture, data model, development rules
```
