"""Repo config discovery and parsing.

Per-repo policy lives in ``bos-universal-config.json`` (or one of the other
discovered names) under a ``managed_file_sync`` section. Every key is optional
and unknown keys are ignored, so newer kit versions can extend the schema
without breaking older callers.
"""

from __future__ import annotations

import importlib.resources
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .markers import DEFAULT_NAMESPACE

CONFIG_SECTION = "managed_file_sync"
DEFAULT_CONFIG_NAMES = (
    "bos-universal-config.json",
    "managed-file-sync.json",
    ".managed-file-sync.json",
)

_TEMPLATE_TOKEN = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


def load_json(path: Path) -> Any:
    """Read a JSON document, reporting parse failures as :class:`ConfigError`."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc


def find_config(root: Path, config_path: str | None = None) -> Path | None:
    """Locate the repo config file, or return ``None`` when there is none."""
    if config_path:
        candidate = Path(config_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        if not candidate.is_file():
            raise ConfigError(f"config file not found: {candidate}")
        return candidate
    for name in DEFAULT_CONFIG_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override dict into base (override wins for scalar conflicts)."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_config_section(config_file: Path | None) -> dict[str, Any]:
    """Read the ``managed_file_sync`` section from a config file.

    Documents without that key are treated as the section itself, which keeps
    standalone ``managed-file-sync.json`` files simple.
    """
    if config_file is None:
        return {}
    data = load_json(config_file)
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be a JSON object: {config_file}")
    section = data.get(CONFIG_SECTION, data)
    if not isinstance(section, dict):
        raise ConfigError(f"'{CONFIG_SECTION}' must be a JSON object: {config_file}")
    return section


def _load_marketplace_config() -> dict[str, Any]:
    """Load the built-in marketplace best practices config.

    Returns the ``managed_file_sync`` section from the bundled marketplace config.
    This is shipped with the action as the base tier (tier 0).
    """
    try:
        # Use importlib.resources to load the marketplace config bundled with the package
        if hasattr(importlib.resources, "files"):
            # Python 3.9+
            files = importlib.resources.files("sync_kit")
            marketplace_data = json.loads(files.joinpath("marketplace-config.json").read_text(encoding="utf-8"))
        else:
            # Fallback for older Python
            import pkg_resources
            marketplace_data = json.loads(
                pkg_resources.resource_string("sync_kit", "marketplace-config.json").decode("utf-8")
            )

        section = marketplace_data.get(CONFIG_SECTION, marketplace_data)
        if not isinstance(section, dict):
            raise ConfigError("marketplace config must contain a 'managed_file_sync' object")
        return section
    except Exception as exc:
        raise ConfigError(f"failed to load marketplace config: {exc}") from exc


def load_repo_config(
    config_file: Path | None = None,
    global_config_file: Path | None = None,
    use_marketplace: bool = True,
) -> dict[str, Any]:
    """Load and merge marketplace + global + repo config.

    Cascade (lower tier wins for scalars, deep merge for objects):
        1. Marketplace config (tier 0) — built-in best practices (default ON)
        2. Global config (tier 1) — org/hub-level overrides
        3. Repo config (tier 2) — repo-specific overrides

    Args:
        config_file: repo-specific config file path (optional).
        global_config_file: org/hub-level config file path (optional).
        use_marketplace: if True (default), merge marketplace config first.
            Can be disabled by passing False or set in any config via use_marketplace_config: false.

    Returns:
        Merged ``managed_file_sync`` section from all applicable tiers, or {} if none provided.

    Raises:
        ConfigError: on invalid config file.
    """
    # Start with marketplace config if enabled
    merged = {}
    if use_marketplace:
        marketplace_section = _load_marketplace_config()
        merged = dict(marketplace_section)
        # Check if any config disables marketplace (user override takes precedence)
        if marketplace_section.get("use_marketplace_config") is False:
            use_marketplace = False
            merged = {}

    # Merge global config on top
    global_section = _load_config_section(global_config_file)
    if global_section:
        # Check if global config disables marketplace
        if global_section.get("use_marketplace_config") is False:
            merged = {}
            use_marketplace = False
        merged = _deep_merge(merged, global_section)

    # Merge repo config on top
    repo_section = _load_config_section(config_file)
    if repo_section:
        # Check if repo config disables marketplace
        if repo_section.get("use_marketplace_config") is False:
            if use_marketplace:
                # Repo explicitly disables; restart from global only
                merged = dict(global_section)
        merged = _deep_merge(merged, repo_section)

    return merged


def parse_service_list(value: str | None) -> list[str]:
    """Parse a comma/whitespace separated service list from an action input."""
    if not value:
        return []
    return [part for part in re.split(r"[,\s]+", value.strip()) if part]


def marker_namespace(section: dict[str, Any]) -> str:
    """Marker namespace for this repo (``managed-file-sync`` by default)."""
    namespace = str(section.get("marker_namespace") or DEFAULT_NAMESPACE).strip()
    if not namespace or ":" in namespace:
        raise ConfigError(f"'marker_namespace' must be non-empty and contain no ':' — got {namespace!r}")
    return namespace


def managed_note(section: dict[str, Any]) -> str | None:
    """Optional provenance note written into managed blocks and file headers."""
    note = section.get("managed_note")
    if note is None or note is False:
        return None
    if isinstance(note, list):
        return "\n".join(str(line) for line in note)
    return str(note) or None


def string_map(value: Any, key: str = "variables") -> dict[str, str]:
    """Coerce a config object into a ``str -> str`` mapping."""
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"'{key}' must be a JSON object of string values")
    return {str(name): str(val) for name, val in value.items()}


def builtin_variables() -> dict[str, str]:
    """Variables always available to service templates."""
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    owner, _, repo = repository.partition("/")
    return {
        "year": str(date.today().year),
        "repository": repository,
        "owner": owner or os.environ.get("GITHUB_REPOSITORY_OWNER", ""),
        "repo": repo,
    }


def render(text: str, variables: dict[str, str]) -> str:
    """Replace ``{{token}}`` placeholders. Unknown tokens are left untouched."""

    def substitute(match: re.Match[str]) -> str:
        return str(variables.get(match.group(1), match.group(0)))

    return _TEMPLATE_TOKEN.sub(substitute, text)
