"""Config loader: merges sai.toml + SAI_* environment variables."""

import os
from pathlib import Path
from typing import Any

from .schema import SaiConfig


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML config file if it exists, else return empty dict."""
    if not path.exists():
        return {}
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]
    with path.open("rb") as f:
        return tomllib.load(f)


def _env_overrides() -> dict[str, Any]:
    """
    Read SAI_* environment variables and convert them into a nested dict.

    Naming convention:
        SAI_<SECTION>_<KEY>  -> data[section][key]
        SAI_<TOP_KEY>        -> data[top_key]

    Examples:
        SAI_LLM_BASE_URL     -> {"llm": {"base_url": "..."}}
        SAI_LOG_LEVEL        -> {"log_level": "..."}
        SAI_SLACK_BOT_TOKEN  -> {"slack": {"bot_token": "..."}}
    """
    # Map env-var segments to config section names (lowercase)
    sections = {"slack", "llm", "memory", "rag", "security", "commands", "database"}
    result: dict[str, Any] = {}

    for key, value in os.environ.items():
        if not key.startswith("SAI_"):
            continue
        rest = key[4:].lower()  # strip SAI_ prefix, lowercase
        parts = rest.split("_", 1)
        if len(parts) == 2 and parts[0] in sections:
            section, field = parts
            result.setdefault(section, {})[field] = value
        else:
            result[rest] = value

    return result


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def load_config(config_path: str | Path = "sai.toml") -> SaiConfig:
    """Load and validate configuration from file + environment."""
    file_data = _load_toml(Path(config_path))
    env_data = _env_overrides()
    merged = _deep_merge(file_data, env_data)
    return SaiConfig.model_validate(merged)
