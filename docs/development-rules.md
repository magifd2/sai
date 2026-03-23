# SAI Development Rules

> 🇯🇵 日本語版: [development-rules.ja.md](development-rules.ja.md)

This document defines the coding standards, conventions, and rules for the SAI project.
**Update this document whenever a feature is added or changed.**

---

## 1. Language & Environment

| Item | Convention |
|------|-----------|
| Language | Python 3.12+ |
| Virtual environment | uv (run via `uv run`) |
| Package management | `pyproject.toml` + `uv.lock` |
| Configuration | `sai.toml` + environment variables (`SAI_` prefix) |

---

## 2. Coding Conventions

### Type Annotations
- All public functions and methods must have type annotations
- All data models must use Pydantic v2 `BaseModel`
- Never pass raw `dict` across module boundaries — use typed models

### Async
- Never block the event loop — DB and file I/O must go through `asyncio.to_thread()` (provided by `sai/db/BaseRepository`)
- Use `httpx.AsyncClient` for all outbound HTTP
- Callers use only `async/await` — internal sync details of the DB layer are invisible to them

### Database Access
- Direct DuckDB access is permitted only inside `sai/db/`
- Raw SQL belongs only in `sai/db/repositories/`
- Always use parameterized queries (`?`). String-format SQL construction is forbidden
- Only `BaseRepository` may call `connection_manager` directly

### Prompts & LLM
- Never interpolate user input directly into a prompt f-string
- All prompt templates live exclusively in `sai/llm/prompts.py`
- User input must pass through `Sanitizer` → `NonceManager.wrap()` before reaching any prompt

### Shell Execution
- `subprocess` calls must use `shell=False` with an argument list
- `eval()`, `exec()`, and `__import__()` are forbidden
- Command execution is allowed only via `sai/commands/executor.py`, which runs only pre-registered scripts
- Parameters are passed to scripts via **stdin JSON** — never as CLI arguments

---

## 3. Security Rules

The event processing pipeline order is mandatory — never reorder:

```
Event received
  → ACL check          ← always first
  → Rate limit check   ← always second
  → Input sanitize     (Sanitizer)
  → Nonce generate + XML encapsulate
  → LLM call
  → Response post-process  (strip think/reasoning tags)
  → Reply to Slack
```

- **No processing before ACL check**
- **Rate limit check must follow immediately after ACL pass**
- Nonces must be generated with `secrets.token_hex(16)` (unpredictable)
- LLM output posted to Slack must be length-truncated; be careful with code block content
- Never log secrets (tokens, API keys)

---

## 4. Testing Rules

- Every module under `sai/` must have a corresponding test file in `tests/unit/`
  - e.g. `sai/security/acl.py` → `tests/unit/test_acl.py`
- All LLM calls in tests must be mocked (`respx` or `unittest.mock`)
- DuckDB tests use an in-memory database (`:memory:`) provided by `tests/conftest.py`
- Security tests must include adversarial inputs: injection attempts, oversized strings, Unicode attacks
- All tests must pass with `uv run pytest` before committing

### Running Tests

```bash
uv run pytest                                        # all tests
uv run pytest tests/unit/                           # unit tests only
uv run pytest tests/integration/                    # integration tests only
uv run pytest --cov=sai --cov-report=term-missing   # with coverage
```

---

## 5. Git & Changelog Rules

### Commit Messages

```
[PhaseN] component: concise description of the change

Examples:
[Phase0] config: add SAI_ prefix to all env vars
[Phase2] security/acl: add blacklist persistence
[Phase4] memory: implement hot→warm lifecycle transition
```

### Branch Strategy
- `main` must always contain working code
- Feature development: `feature/<name>` branch
- Bug fixes: `fix/<name>` branch

### CHANGELOG.md
Use [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format.

Sections per release:
- `Added` — new features
- `Changed` — changes to existing features
- `Fixed` — bug fixes
- `Security` — security-related changes
- `Deprecated` — features that will be removed
- `Removed` — removed features

---

## 6. Documentation Rules

| Document | Location | When to update |
|----------|----------|----------------|
| Feature descriptions | `docs/features/` | On feature add/change |
| Architecture | `docs/architecture.md` | On structural change |
| Data model | `docs/data-model.md` | On schema change |
| API spec | `docs/api.md` | On interface change |
| Development rules | `docs/development-rules.md` | On rule change |
| Changelog | `CHANGELOG.md` | On release |

- **Always update documentation when adding or changing a feature**
- All documents are provided in both English (`*.md`) and Japanese (`*.ja.md`)
- Code comments only where logic is non-obvious
- Public functions get a concise docstring; types are expressed via annotations

---

## 7. Prohibited

- Committing `.env` files (only `.env.example` is allowed)
- Committing database files (`data/*.db`) or vector store data (`data/chroma/`)
- Skipping commit hooks with `--no-verify`
- Hardcoded secrets (tokens, passwords) anywhere in source
- `shell=True` in any `subprocess` call
- Direct access to `connection_manager` outside the `sai/db/` layer
