"""Repo config discovery and parsing.

Per-repo policy lives in ``.github/bos-universal-config.json`` (preferred) or
one of the other discovered names under a ``managed_file_sync`` section. Every
key is optional and unknown keys are ignored, so newer kit versions can extend
the schema without breaking older callers.
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
MARKETPLACE_CONFIG_FILE = "blackout-secure-managed-file-sync-marketplace-config.json"
DEFAULT_CONFIG_PATHS = (
    ".github/bos-universal-config.json",
    "bos-universal-config.json",
    "managed-file-sync.json",
    ".managed-file-sync.json",
)

# Backward compatibility for callers importing the legacy constant name.
DEFAULT_CONFIG_NAMES = DEFAULT_CONFIG_PATHS

_TEMPLATE_TOKEN = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
_RUNNER_LABEL = re.compile(r"^[A-Za-z0-9_.-]+$")
_MARKER_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]+$")

FALLBACK_DEFAULT_RUNNER = "ubuntu-latest"
DEFAULT_SYNC_DIRECTION = "source-to-destination"


def load_json(path: Path) -> Any:
    """Read a JSON document, reporting parse failures as :class:`ConfigError`."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"file not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"config file must be UTF-8 text: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"failed to read config file {path}: {exc}") from exc


def find_config(root: Path, config_path: str | None = None) -> Path | None:
    """Locate the repo config file, or return ``None`` when there is none."""
    if config_path:
        candidate = Path(config_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        if not candidate.is_file():
            raise ConfigError(f"config file not found: {candidate}")
        return candidate
    for rel_path in DEFAULT_CONFIG_PATHS:
        candidate = root / rel_path
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


def _append_unique(base_values: list[Any], extra_values: list[Any]) -> list[str]:
    """Append values preserving order and removing duplicates."""
    merged: list[str] = []
    seen: set[str] = set()
    for raw in [*base_values, *extra_values]:
        value = str(raw)
        if value in seen:
            continue
        seen.add(value)
        merged.append(value)
    return merged


def _bool_field(value: Any, key: str, default: bool) -> bool:
    """Read a strict boolean config field."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ConfigError(f"'{key}' must be true or false")


def _string_list(value: Any, key: str) -> list[str]:
    """Normalize a config list to strings, validating the type."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"'{key}' must be a JSON array")
    return [str(item) for item in value]


def _merge_section(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge a config tier with service/exclusion list semantics."""
    merged = _deep_merge(base, override)

    base_services = base.get("services")
    override_services = override.get("services")
    use_marketplace_services = _bool_field(
        override.get("use_marketplace_services"),
        "use_marketplace_services",
        True,
    )
    if isinstance(base_services, list) and isinstance(override_services, list):
        merged["services"] = (
            _append_unique(base_services, override_services)
            if use_marketplace_services
            else [str(item) for item in override_services]
        )
    elif isinstance(override_services, list):
        merged["services"] = [str(item) for item in override_services]
    elif override_services is not None and not isinstance(override_services, dict):
        raise ConfigError("'services' must be a list or an object of name -> bool")

    for key in ("exclude_services", "disabled_services"):
        base_value = base.get(key)
        override_value = override.get(key)
        if isinstance(base_value, list) and isinstance(override_value, list):
            merged[key] = _append_unique(base_value, override_value)
        elif override_value is not None:
            merged[key] = _string_list(override_value, key)

    return merged


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


def load_inline_config(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    """Parse an inline JSON object and return the managed_file_sync section."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        data = raw
    else:
        if not isinstance(raw, str):
            raise ConfigError("inline config must be a JSON string or object")
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid inline config JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("inline config JSON must decode to an object")
    section = data.get(CONFIG_SECTION, data)
    if not isinstance(section, dict):
        raise ConfigError("'managed_file_sync' must be a JSON object in the inline config")
    return section


def _load_bundled_config(path: str, *, label: str) -> dict[str, Any]:
    """Load a bundled config section from this package."""
    try:
        files = importlib.resources.files("sync_kit")
        config_data = json.loads(
            files.joinpath(path).read_text(encoding="utf-8")
        )

        section = config_data.get(CONFIG_SECTION, config_data)
        if not isinstance(section, dict):
            raise ConfigError(f"{label} config must contain a 'managed_file_sync' object")
        return section
    except Exception as exc:
        raise ConfigError(f"failed to load {label} config: {exc}") from exc


def _load_marketplace_config() -> dict[str, Any]:
    """Load switchable marketplace best-practice defaults."""
    return _load_bundled_config(MARKETPLACE_CONFIG_FILE, label="marketplace")


def load_repo_config(
    config_file: Path | None = None,
    global_config_file: Path | None = None,
    use_marketplace: bool = True,
    config_json: str | dict[str, Any] | None = None,
    global_config_json: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load and merge marketplace + global + repo + inline config.

    Cascade (lower tier wins for scalars, deep merge for objects):
        1. Marketplace config (switchable built-in defaults)
        2. Global config (org/hub-level overrides)
        3. Repo config (repo-specific overrides)
        4. Inline config JSON for each tier (highest-precedence override for workflow runs)

    Args:
        config_file: repo-specific config file path (optional).
        global_config_file: org/hub-level config file path (optional).
        use_marketplace: if True (default), merge marketplace config first.
            Can be disabled by passing False or set in any config via use_marketplace_config: false.
        config_json: raw inline repo config JSON object or serialized object string.
        global_config_json: raw inline global config JSON object or serialized object string.

    Returns:
        Merged ``managed_file_sync`` section from all applicable tiers, or {} if none provided.

    Raises:
        ConfigError: on invalid config file.
    """
    global_section = _load_config_section(global_config_file)
    global_inline_section = load_inline_config(global_config_json)
    repo_section = _load_config_section(config_file)
    repo_inline_section = load_inline_config(config_json)

    marketplace_enabled = use_marketplace
    for section in (
        global_section,
        global_inline_section,
        repo_section,
        repo_inline_section,
    ):
        if "use_marketplace_config" not in section:
            continue
        configured = _bool_field(
            section["use_marketplace_config"],
            "use_marketplace_config",
            marketplace_enabled,
        )
        if use_marketplace:
            marketplace_enabled = configured

    merged: dict[str, Any] = {}
    if marketplace_enabled:
        marketplace_section = _load_marketplace_config()
        if _bool_field(
            marketplace_section.get("use_marketplace_config"),
            "use_marketplace_config",
            True,
        ):
            merged = _merge_section(merged, marketplace_section)

    for section in (global_section, global_inline_section, repo_section, repo_inline_section):
        if section:
            merged = _merge_section(merged, section)

    return merged


def parse_service_list(value: str | None) -> list[str]:
    """Parse a comma/whitespace separated service list from an action input."""
    if not value:
        return []
    return [part for part in re.split(r"[,\s]+", value.strip()) if part]


def marker_identifier(value: Any, key: str) -> str:
    """Validate a service or namespace token embedded in managed markers."""
    identifier = str(value).strip()
    if not _MARKER_IDENTIFIER.fullmatch(identifier):
        raise ConfigError(f"'{key}' must contain only letters, numbers, '.', '_', or '-'")
    return identifier


def marker_namespace(section: dict[str, Any]) -> str:
    """Marker namespace for this repo (``managed-file-sync`` by default)."""
    return marker_identifier(
        section.get("marker_namespace") or DEFAULT_NAMESPACE,
        "marker_namespace",
    )


def sync_direction(section: dict[str, Any]) -> str:
    """Return the supported one-way sync direction."""
    direction = section.get("direction", DEFAULT_SYNC_DIRECTION)
    if direction != DEFAULT_SYNC_DIRECTION:
        raise ConfigError(
            "'direction' must be 'source-to-destination'; reverse and "
            "bidirectional sync are not supported"
        )
    return direction


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


def builtin_variables(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Variables always available to templates, with normalized runner overrides."""
    overrides = overrides or {}
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    owner, _, repo = repository.partition("/")
    fallback = _runner_or_fallback(
        overrides.get("fallback_default_runner"),
        FALLBACK_DEFAULT_RUNNER,
    )
    default_runner = _runner_or_fallback(
        overrides.get("DEFAULT_RUNNER", os.environ.get("DEFAULT_RUNNER")),
        fallback,
    )
    runner_x64 = _runner_or_fallback(
        overrides.get("RUNNER_X64", os.environ.get("RUNNER_X64")),
        fallback,
    )
    runner_arm64 = _runner_or_fallback(
        overrides.get("RUNNER_ARM64", os.environ.get("RUNNER_ARM64")),
        fallback,
    )
    workload_arch = _workload_arch_value(
        os.environ.get("MFS_WORKLOAD_ARCH", overrides.get("WORKLOAD_ARCH"))
    )
    selected_runner = _select_runner_for_workload(
        workload_arch=workload_arch,
        default_runner=default_runner,
        runner_x64=runner_x64,
        runner_arm64=runner_arm64,
        runtime_runner_arch=os.environ.get("RUNNER_ARCH"),
    )
    variables = {
        "year": str(date.today().year),
        "repository": repository,
        "owner": owner or os.environ.get("GITHUB_REPOSITORY_OWNER", ""),
        "repo": repo,
        "project_name": repo,
    }
    variables.update(overrides)
    variables.update(
        {
            "fallback_default_runner": fallback,
            "DEFAULT_RUNNER": default_runner,
            "RUNNER_X64": runner_x64,
            "RUNNER_ARM64": runner_arm64,
            "WORKLOAD_ARCH": workload_arch,
            "SELECTED_RUNNER": selected_runner,
        }
    )
    return variables


def _runner_or_fallback(value: str | None, fallback: str) -> str:
    """Return a valid runner label (or JSON array) or a safe fallback.

    Valid values:
    - a single runner label (for example ``ubuntu-latest``)
    - a JSON array string of labels (for example ``[\"ubuntu-latest\"]``)
    """
    if value is None:
        return fallback

    normalized = value.strip()
    if not normalized:
        return fallback

    # Support runner matrices passed as JSON array strings.
    if normalized.startswith("[") and normalized.endswith("]"):
        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError:
            return fallback
        if (
            isinstance(parsed, list)
            and parsed
            and all(isinstance(item, str) and item.strip() and _RUNNER_LABEL.fullmatch(item.strip()) for item in parsed)
        ):
            return normalized
        return fallback

    return normalized if _RUNNER_LABEL.fullmatch(normalized) else fallback


def _workload_arch_value(value: str | None) -> str:
    """Normalize workload arch selection from environment.

    Allowed values: ``auto`` (default), ``x64``, ``arm64``, ``default``.
    Unknown values degrade to ``auto``.
    """
    if value is None:
        return "auto"
    normalized = value.strip().lower()
    if normalized in {"x64", "amd64"}:
        return "x64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    if normalized in {"default", "any"}:
        return "default"
    return "auto"


def _select_runner_for_workload(
    *,
    workload_arch: str,
    default_runner: str,
    runner_x64: str,
    runner_arm64: str,
    runtime_runner_arch: str | None,
) -> str:
    """Pick the runner label from workload preference or runtime auto-detection."""
    if workload_arch == "x64":
        return runner_x64
    if workload_arch == "arm64":
        return runner_arm64
    if workload_arch == "default":
        return default_runner

    runtime_arch = (runtime_runner_arch or "").strip().lower()
    if runtime_arch in {"x64", "amd64"}:
        return runner_x64
    if runtime_arch in {"arm64", "aarch64"}:
        return runner_arm64
    return default_runner


def render(text: str, variables: dict[str, str]) -> str:
    """Replace ``{{token}}`` placeholders. Unknown tokens are left untouched."""

    def substitute(match: re.Match[str]) -> str:
        return str(variables.get(match.group(1), match.group(0)))

    return _TEMPLATE_TOKEN.sub(substitute, text)
