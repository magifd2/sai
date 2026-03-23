# AGENTS.md — SAI Project Guide for AI Agents

This file is read automatically by Claude Code and other AI coding agents.
It defines the rules, constraints, and conventions that must be followed when working in this repository.

---

## Project Overview

SAI is a Slack bot that:
- Monitors channel messages in real time via WebSocket (Slack Socket Mode)
- Stores messages in a memory system with automatic lifecycle management (HOT → WARM → COLD → ARCHIVE)
- Permanently stores messages that receive a configured reaction (PINNED state)
- Answers @mention questions using RAG over stored memories
- Generates on-demand summaries of a channel or thread (`summarize_channel` / `summarize_thread` intents)
- Executes pre-registered shell scripts via natural language command interpretation
- Runs entirely on a local LLM via LM Studio (OpenAI-compatible API)

**Primary language:** Python 3.12+
**Package manager:** uv — always use `uv run` to execute commands
**Database:** DuckDB + VSS extension (single file, no external server)

---

## Essential Commands

```bash
# Install / sync dependencies
uv sync

# Run all tests (required before every commit)
uv run pytest

# Run with coverage
uv run pytest --cov=sai --cov-report=term-missing

# Initialize / migrate the database schema (safe, keeps existing data)
uv run sai init-db

# Reset the database — drops ALL data and recreates schema from scratch
uv run sai init-db --reset          # prompts for confirmation
uv run sai init-db --reset --yes    # skips confirmation (for scripts)

# Check LLM connectivity
uv run sai check

# Start the bot
uv run sai start

# Memory monitoring (run while SAI is stopped)
uv run sai memory stats                          # record counts by state
uv run sai memory list [--state hot|warm|cold|pinned] [--user ID] [--channel ID] [--limit N]
uv run sai memory show <record-id-or-prefix>     # full detail of one record
```

**Always run `uv run pytest` and confirm all tests pass before committing.**

---

## Architecture Constraints — Read Before Touching Code

### DB layer is fully encapsulated

- DuckDB access is **only permitted inside `sai/db/`**
- Raw SQL is **only permitted inside `sai/db/repositories/`**
- `connection_manager` is **only called from `BaseRepository`**
- All repository public methods are `async` — callers never see `asyncio.to_thread` or DuckDB internals
- Always use parameterized queries (`?`). Never build SQL by string formatting.

### Event processing pipeline is ordered and must not be reordered

```
parse_event()
  → stale event guard  ← drop events older than startup_time − 30 s
  → dedup guard        ← drop re-delivered events (key: ts#channel_id#event_type)
  → ACL check          ← FIRST security check, always
  → rate limit check   ← SECOND always
  → sanitize input
  → nonce + XML wrap
  → planner (intent → action)
  → dispatch:
      command          → execute script + audit log
      summarize_*      → fetch records + LLM summary
      rag / none       → RAG retrieval + LLM answer
  → strip response tags
  → post to Slack
```

Defined in `sai/app.py`. The stale/dedup guards run before ACL as they are infrastructure-level filters, not security checks. Do not add security processing before the ACL check.

### Prompt construction is centralized

- All prompt templates live in `sai/llm/prompts.py` — nowhere else
- User input must go through `sanitize()` → `nonce_mod.wrap()` before any LLM prompt
- Never interpolate user input directly into an f-string prompt

### Command scripts receive parameters via stdin JSON — never CLI args

```python
# executor.py sends this to the script's stdin:
{"user_id": "U123", "command": "cmd_name", "args": {"key": "value"}}
```

Scripts read with `params=$(cat)` then parse with Python json. Do not pass arguments as CLI positional params.

---

## Memory States

| State | Age | Content | Lifecycle |
|-------|-----|---------|-----------|
| `hot` | < 24h | Full original text | Ages to `warm` |
| `warm` | 1–7 days | LLM summary | Ages to `cold` |
| `cold` | > 7 days | Awaiting removal | Archived |
| `pinned` | Any | Full text | **Never transitions — skip in all lifecycle code** |

`PINNED` records must be excluded from all aging and archival queries.
The `find_older_than()` and `find_by_state()` queries in `MemoryRepository` already exclude pinned records by state; keep it that way.

---

## Security Rules — Non-Negotiable

- `eval()`, `exec()`, `__import__()` are **forbidden** everywhere
- `subprocess` calls must use `shell=False` with an argument list
- Never log tokens, API keys, or nonce values
- Nonces are generated with `secrets.token_hex(16)` — do not use `random` or `uuid` for nonces
- Never skip the ACL check or rate limit check, even in test helpers or admin paths

---

## Testing Rules

- Every module in `sai/` must have a corresponding test in `tests/unit/test_<module>.py`
- LLM calls must be mocked in all tests (`respx` for HTTP, `unittest.mock` for direct calls)
- DB tests use the in-memory DuckDB fixture from `tests/conftest.py` — never write to a real file in tests
- Security tests must include adversarial inputs: injection strings, oversized input, Unicode control characters

---

## Documentation Rules

All user-facing documentation is provided in two languages:

| English | Japanese |
|---------|----------|
| `README.md` | `README.ja.md` |
| `docs/development-rules.md` | `docs/development-rules.ja.md` |
| `docs/slack-setup.md` | `docs/slack-setup.ja.md` |

**When modifying a document, update both language versions.**
Each file links to its counterpart at the top.

---

## Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>: concise description

Types: feat, fix, chore, docs, refactor, test, perf
```

- Use English for commit messages
- Update `CHANGELOG.md` under `[Unreleased]` for every meaningful change

---

## Configuration

- All environment variables use the `SAI_` prefix (e.g. `SAI_SLACK_BOT_TOKEN`)
- Config schema is defined in `config/schema.py` (Pydantic v2)
- New config options must be added to `config/schema.py`, `.env.example`, and both README files

---

## Release Procedure

Releases are managed manually. No CI/CD automation.

```bash
# 1. Update CHANGELOG.md
#    - Move all items under [Unreleased] to a new [x.y.z] - YYYY-MM-DD section
#    - Add a link at the bottom: [x.y.z]: https://github.com/magifd2/sai/releases/tag/vx.y.z
#    - Leave [Unreleased] section empty (but present) for future entries

# 2. Commit
git add CHANGELOG.md
git commit -m "chore: prepare vX.Y.Z release"

# 3. Tag and push
git tag vX.Y.Z
git push origin main
git push origin vX.Y.Z

# 4. Create GitHub Release
gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."
```

---

## Files Never to Commit

- `.env` (credentials)
- `data/*.db`, `data/*.db-wal`, `data/*.db-shm` (database files)
- `data/chroma/`, `data/sandbox/` (runtime data)
- Any file containing hardcoded secrets or tokens
