# SAI — Slack AI Command Interpreter

> 🇯🇵 日本語版: [README.ja.md](README.ja.md)

A context-aware Slack bot that remembers your team's conversations, answers questions grounded in history, and executes commands via natural language — all powered by a local LLM.

---

## What SAI Can Do

### 1. Answer questions from conversation history

SAI silently reads every message posted in its joined channels and stores them in memory. When you @mention SAI, it retrieves relevant past conversations and uses them as context for its answer.

```
Alice  │ @SAI What did Bob say about the deployment schedule last week?
───────┼────────────────────────────────────────────────────────────────
SAI    │ Based on the conversation from Tuesday, Bob mentioned that the
       │ deployment is planned for Friday at 2:00 PM JST, but noted
       │ there may be a delay if the staging tests don't pass by Thursday.
```

```
Alice  │ @SAI Has anyone discussed the Redis migration?
───────┼────────────────────────────────────────────────────────────────
SAI    │ Yes — Carol brought it up on Monday. She suggested migrating
       │ from Redis 6 to Redis 7 during the maintenance window on the
       │ 25th. Dave replied that he wanted to review the breaking changes
       │ first and would share a summary by end of week.
```

---

### 2. Execute commands via natural language

SAI can run pre-registered shell scripts in response to natural language requests. You don't need to remember command names — just describe what you want.

```
Bob    │ @SAI Can you check the server status?
───────┼────────────────────────────────────────────────────────────────
SAI    │ ✅ `server_status`:
       │ ```
       │ Hostname : prod-server-01
       │ Uptime   : up 14 days, 3 hours
       │ Load avg : 0.42, 0.38, 0.35
       │
       │ Memory:
       │ total   used   free
       │ 32Gi    12Gi   18Gi
       │ ```
```

```
Carol  │ @SAI How much disk space is left on /var/log?
───────┼────────────────────────────────────────────────────────────────
SAI    │ ✅ `disk_usage`:
       │ ```
       │ Filesystem  Size  Used  Avail  Use%
       │ /dev/sda1    50G   31G    19G   62%
       │
       │ Top directories:
       │ 8.2G  /var/log/nginx
       │ 4.1G  /var/log/app
       │ 1.3G  /var/log/syslog
       │ ```
```

```
Dave   │ @SAI ping google.com for me
───────┼────────────────────────────────────────────────────────────────
SAI    │ ✅ `ping_host`:
       │ ```
       │ PING google.com: 4 packets, 0% loss
       │ min/avg/max = 4.2/4.8/5.3 ms
       │ ```
```

---

### 3. Pin important messages permanently

Add a 📌 reaction (or ⭐ 🔖 📝) to any message and SAI will store it in **pinned memory** — it will never be summarized, never be archived, and will always be available as context for future answers.

```
Eve    │ The production DB password rotation is scheduled for Dec 1st.
       │ All services must update their credentials by Nov 30th 5PM.
       │
       │  [someone adds 📌 reaction]
       │
Alice  │ @SAI When is the DB password rotation?
───────┼────────────────────────────────────────────────────────────────
SAI    │ The production DB password rotation is scheduled for December
       │ 1st. All services need to update credentials by November 30th
       │ at 5:00 PM.
```

> Even months later, pinned messages remain available — unlike regular messages which are gradually summarized and eventually archived.

---

### 4. Smart memory with automatic forgetting

SAI manages its own memory so it doesn't grow forever. Regular messages follow this lifecycle:

```
HOT    (< 24h)    Full original text — every detail preserved
  ↓
WARM   (1–7 days) LLM-generated summary — key points kept
  ↓
COLD   (> 7 days) Marked for removal from active memory
  ↓
ARCHIVE           Moved to cold storage, no longer retrieved

PINNED            Reaction-triggered — never ages, never archived
```

This means SAI has good recall for recent events and useful summaries for older ones, while staying within the LLM's context window.

---

### 5. Thread continuation

Reply to any thread that SAI has already participated in — without needing to @mention SAI again — and the conversation continues naturally. SAI detects that the parent message is in memory and treats the reply as a mention automatically.

---

### What SAI Does NOT Do

- SAI does **not** proactively send messages — it only replies when @mentioned
- SAI does **not** run arbitrary shell commands — only pre-registered scripts in `scripts/commands.json`
- SAI does **not** have internet access — it uses a locally running LLM

---

## Requirements

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- [LM Studio](https://lmstudio.ai/) (or any OpenAI-compatible local API)
- Slack app with Socket Mode enabled — see [docs/slack-setup.md](docs/slack-setup.md)

---

## Quick Start

```bash
# 1. Install dependencies
uv sync

# 2. Copy and fill in your credentials
cp .env.example .env
# Edit .env with SAI_SLACK_BOT_TOKEN and SAI_SLACK_APP_TOKEN

# 3. (Optional) Copy and customize the full config
cp sai.toml.example sai.toml
# Edit sai.toml — set workspace_name, response_language, model names, etc.
# sai.toml is read from the current directory where you run `uv run sai start`

# 4. Initialize the database
uv run sai init-db

# 5. Verify LLM connectivity
uv run sai check

# 6. Start the bot
uv run sai start
```

---

## Configuration

Settings are loaded from `sai.toml` (read from the current directory by default, override with `--config`) and `SAI_*` environment variables. Environment variables override the config file.

| Variable | Default | Description |
|----------|---------|-------------|
| `SAI_SLACK_BOT_TOKEN` | *(required)* | Slack bot token (`xoxb-...`) |
| `SAI_SLACK_APP_TOKEN` | *(required)* | Socket Mode app token (`xapp-...`) |
| `SAI_SLACK_RESPONSE_LANGUAGE` | *(auto-detect)* | Language for bot replies (e.g. `Japanese`, `English`) |
| `SAI_LLM_BASE_URL` | `http://localhost:1234/v1` | LM Studio endpoint |
| `SAI_LLM_API_KEY` | `lm-studio` | API key |
| `SAI_LLM_MODEL` | `openai/gpt-oss-20b` | Chat model |
| `SAI_LLM_EMBED_MODEL` | `text-embedding-nomic-embed-text-v1.5` | Embedding model |
| `SAI_LLM_MAX_CONCURRENT_REQUESTS` | `4` | Max parallel LLM requests |
| `SAI_MEMORY_PIN_REACTIONS` | `pushpin,star,bookmark,memo` | Reactions that pin memory |
| `SAI_LOG_LEVEL` | `INFO` | Log level |

For all available settings with descriptions and defaults, see [`sai.toml.example`](sai.toml.example).
Secrets (tokens, API keys) can be placed in `.env` — see [`.env.example`](.env.example).

---

## Adding Custom Commands

**1.** Write a shell script in `scripts/`. Parameters arrive as JSON on stdin:

```bash
#!/usr/bin/env bash
# scripts/my_command.sh
params=$(cat)
target=$(echo "$params" | python3 -c "
import json, sys
print(json.load(sys.stdin)['args']['target'])
")
echo "Running check on: $target"
# ... your logic here
```

**2.** Register it in `scripts/commands.json`:

```json
{
  "name": "my_command",
  "description": "Check the health of a given service",
  "script_path": "my_command.sh",
  "required_args": ["target"],
  "max_runtime_seconds": 30
}
```

SAI's LLM will automatically map user requests like *"check the health of nginx"* to this command.

---

## Security

SAI is designed with multiple layers of defense:

- **ACL** — whitelist/blacklist by Slack user ID
- **Rate limiting** — per-user sliding window (configurable per minute and per hour)
- **Prompt injection defense** — per-request nonce XML encapsulation, input sanitizer, role-separated prompts
- **Command sandboxing** — only pre-registered scripts run; parameters via stdin JSON (never CLI args); resource limits applied
- **Response sanitization** — model internal tags (`<think>`, `[THINK]`, `<reasoning>`, etc.) are stripped before posting to Slack

See [docs/development-rules.md](docs/development-rules.md) for the full security policy.

---

## Running Tests

```bash
uv run pytest
uv run pytest --cov=sai --cov-report=term-missing
```

---

## Project Structure

```
sai/
├── config/              # Configuration schema and loader
├── sai/
│   ├── app.py           # Application orchestrator — event pipeline
│   ├── db/              # DuckDB + VSS repository layer (async interface)
│   ├── llm/             # LLM client, prompts, nonce, sanitizer
│   ├── memory/          # Memory models, lifecycle state machine, scheduler
│   ├── rag/             # Embedding generation and retrieval
│   ├── security/        # ACL, rate limiter, injection detection
│   ├── slack/           # Socket Mode handler, event parser, cache
│   ├── commands/        # Registry, NL interpreter, executor
│   └── utils/           # Logging, time helpers, ID generation
├── scripts/             # Command scripts + commands.json manifest
├── tests/               # Unit and integration tests
└── docs/                # Setup guides, architecture, development rules
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/slack-setup.md](docs/slack-setup.md) / [ja](docs/slack-setup.ja.md) | Step-by-step Slack app setup guide |
| [docs/development-rules.md](docs/development-rules.md) / [ja](docs/development-rules.ja.md) | Coding standards, security rules, git conventions |
