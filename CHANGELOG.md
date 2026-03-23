# Changelog

All notable changes to SAI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- Initial project scaffold with uv
- Configuration system (`config/schema.py`, `config/loader.py`) with `SAI_` env var prefix
- DuckDB + VSS backend for unified structured data and vector similarity search
- Repository pattern (`sai/db/`) abstracting all DB access behind async interfaces
- Memory lifecycle system: HOT → WARM → COLD → ARCHIVE state machine
- PINNED memory state: reaction-triggered persistent memory that never ages or archives
- Background scheduler for automatic memory aging and archival
- LLM client with OpenAI-compatible API, retry logic, and configurable concurrency limit (`SAI_LLM_MAX_CONCURRENT_REQUESTS`)
- Prompt injection defense: nonce XML encapsulation, input sanitizer, role-separated prompts
- Model-specific tag stripping: `<think>`, `<thinking>`, `<reasoning>`, `[THINK]`, `[THINKING]`, `[REASONING]` (Mistral-style)
- ACL enforcement with whitelist/blacklist, bot detection
- Per-user rate limiting (sliding window, minute + hour limits)
- Process guard for subprocess lifecycle management
- Slack Socket Mode event listener with immediate ACK
- Two-layer user/channel cache (in-memory + DuckDB)
- Command interpreter: NL → command registry via LLM with strict integer parsing
- Command executor: stdin JSON parameter passing (no CLI arg injection surface)
- RAG retriever using DuckDB HNSW index
- Sample command scripts (`server_status`, `disk_usage`, `ping_host`)
- Development rules documentation (`docs/development-rules.md`)
