"""Blackout Secure Managed File Sync — config-driven repo file standardisation.

Public surface:

    from sync_kit import load_repo_config, load_catalog, resolve_services, SyncEngine
"""

from __future__ import annotations

from ._version import __version__
from .ai import AISettings, Provider, detect_provider, summarize
from .catalog import check_conflicts, load_catalog, parse_service, resolve_services
from .config import (
    CONFIG_SECTION,
    DEFAULT_CONFIG_NAMES,
    ai_settings,
    find_config,
    load_repo_config,
    managed_note,
    parse_service_list,
)
from .engine import Change, SyncEngine, SyncResult
from .errors import ConfigError, MarkerError, SyncKitError
from .markers import DEFAULT_NAMESPACE, apply_block, comment_prefix_for, render_block
from .metadata import (
    RESERVED_METADATA_KEYS,
    package_metadata,
    strip_package_metadata,
)

__all__ = [
    "CONFIG_SECTION",
    "DEFAULT_CONFIG_NAMES",
    "DEFAULT_NAMESPACE",
    "RESERVED_METADATA_KEYS",
    "AISettings",
    "Change",
    "ConfigError",
    "MarkerError",
    "Provider",
    "SyncEngine",
    "SyncKitError",
    "SyncResult",
    "__version__",
    "ai_settings",
    "apply_block",
    "check_conflicts",
    "comment_prefix_for",
    "detect_provider",
    "find_config",
    "load_catalog",
    "load_repo_config",
    "managed_note",
    "package_metadata",
    "parse_service",
    "parse_service_list",
    "render_block",
    "resolve_services",
    "strip_package_metadata",
    "summarize",
]
