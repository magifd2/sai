# Changelog

All notable changes to SAI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- Memory monitoring CLI: `sai memory stats`, `sai memory list`, `sai memory show` — inspect memory database contents while SAI is stopped; DB opened in read-only mode

---

## [0.1.0] - 2026-03-24

### Added

#### Core architecture
- Initial project scaffold with uv
- Configuration system (`config/schema.py`, `config/loader.py`) with `SAI_` env var prefix; `sai.toml` as primary config (read from current directory, override with `--config`), `.env` for secrets
- DuckDB + VSS backend for unified structured data and vector similarity search
- Repository pattern (`sai/db/`) abstracting all DB access behind async interfaces
- Memory lifecycle system: HOT → WARM → COLD → ARCHIVE state machine
- PINNED memory state: reaction-triggered persistent memory that never ages or archives
- Background scheduler for automatic memory aging and archival
- LLM client with OpenAI-compatible API, retry logic, and configurable concurrency limit (`SAI_LLM_MAX_CONCURRENT_REQUESTS`)
- ACL enforcement with whitelist/blacklist, bot detection
- Per-user rate limiting (sliding window, minute + hour limits)
- Process guard for subprocess lifecycle management
- Slack Socket Mode event listener with immediate ACK
- Two-layer user/channel cache (in-memory + DuckDB)
- RAG retriever using DuckDB HNSW index
- Sample command scripts (`server_status`, `disk_usage`, `ping_host`)
- Development rules documentation (`docs/development-rules.md`)

#### LLM & prompting
- Hierarchical ActionPlanner: single LLM call produces structured intent analysis with action (`command` / `rag` / `none`), command index, extracted args, and optimized RAG query
- Command interpreter: NL → command registry via LLM with strict integer parsing
- Command executor: stdin JSON parameter passing (no CLI arg injection surface)
- Prompt injection defense: per-request nonce XML encapsulation, input sanitizer (invisible Unicode stripping, Slack link token expansion, XML tag removal), role-separated prompts
- Slack link token expansion in sanitizer: `<http://url|label>` → `label`, `<@U…>` → `@U…` — prevents auto-linked URLs from being stripped as XML tags
- Model-specific tag stripping: `<think>`, `<thinking>`, `<reasoning>`, `[THINK]`, `[THINKING]`, `[REASONING]` (Mistral-style) removed before posting to Slack
- RAG prompt: three-case answering rule (capabilities from system prompt / chitchat naturally / history from RAG only), requester identity (`user_id + display_name`), speaker identity in context snippets
- Response language setting (`SAI_SLACK_RESPONSE_LANGUAGE`) with auto-detect fallback using Japanese/CJK heuristic; language instruction placed in user turn for small-model compliance
- Bot responses stored in HOT memory immediately after posting, enabling follow-up correction instructions via RAG

#### Slack output
- Markdown → Slack Block Kit structural converter: `## heading` → header block, ` ``` ` → section code block, `---` → divider block, `| table |` → native Slack table block, everything else accumulated as raw mrkdwn text
- Markdown inline normalization: `**bold**` → `*bold*`, `__bold__` → `*bold*`, `~~strike~~` → `~strike~`, `- list` → `•` / `◦` (nested)
- Native Slack table block support with correct API format: rows as arrays of `{"type": "raw_text", "text": "..."}` cell arrays
- `split_blocks_for_slack()`: splits block lists at table boundaries for messages with multiple tables (Slack allows only one table block per message)
- Thread continuation: replies to threads SAI has participated in are automatically treated as @mentions

#### Observability
- LLM request/response audit logging: model, message count, max_tokens, temperature, prompt_tokens, completion_tokens (prompt content intentionally excluded for privacy)
- httpx/httpcore log suppression at WARNING level in non-DEBUG mode (prevents plain-text lines from breaking JSON log stream)

### Fixed
- `ProcessGuard` was implemented but never invoked; integrated into `MemoryScheduler` (runs every 5 seconds via `asyncio.to_thread`)
- `main.py` was creating duplicate `SlackClient` / `ACLRepository` / `CacheManager` instances; refactored with `_AppBundle` dataclass
- `LLMClient.chat()` could raise `IndexError` on empty `choices` list; added explicit guard
- `memory.py` used `SELECT *`; replaced with explicit `_COLS` constant to prevent silent column-order breakage
- `command_log.py` used `SELECT *`; replaced with explicit `_COLS` / `_SELECT` constants
- Removed unused `_cache` dict from `RateLimiter` (dead code)
- Removed stale `chroma_path` / `collection_name` fields from `RagConfig` (ChromaDB was replaced by DuckDB VSS)
- Embedding dimension (`EMBED_DIM`) was a hardcoded constant; now configurable via `llm.embed_dim` config key (default: 768)
- `setup_logging()` used case-sensitive `level == "DEBUG"` check; fixed to `level.upper() == "DEBUG"`
- `Awaitable` import in `output_parser.py` was incorrectly placed after function definitions; moved to top-of-file
- Slack table block cell format was `{"raw_text": "..."}` (invalid); corrected to `{"type": "raw_text", "text": "..."}` with rows as arrays of arrays
- `_SLACK_BARE_RE` in sanitizer was too broad (`<([^>]+)>`) and matched XML/HTML tags like `<script>`; restricted to Slack-specific patterns only (http/https/ftp URLs, `@U…` mentions, `#C…` channels, `!…` tokens)
- RAG prompt incorrectly applied "answer only from context" rule to capability and chitchat questions, causing "not in context" responses to "what can you do?"

[0.1.0]: https://github.com/magifd2/sai/releases/tag/v0.1.0
