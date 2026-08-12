"""Blackout Secure Managed File Sync — config-driven repo file standardisation.

Public surface:

    from sync_kit import load_repo_config, load_catalog, resolve_services, SyncEngine
"""

from __future__ import annotations

from .catalog import check_conflicts, load_catalog, parse_service, resolve_services
from .config import (
    CONFIG_SECTION,
    DEFAULT_CONFIG_NAMES,
    find_config,
    load_repo_config,
    managed_note,
    parse_service_list,
)
from .engine import Change, SyncEngine, SyncResult
from .errors import ConfigError, MarkerError, SyncKitError
from .markers import DEFAULT_NAMESPACE, apply_block, comment_prefix_for, render_block

__version__ = "1.0.0"

__all__ = [
    "CONFIG_SECTION",
    "DEFAULT_CONFIG_NAMES",
    "DEFAULT_NAMESPACE",
    "Change",
    "ConfigError",
    "MarkerError",
    "SyncEngine",
    "SyncKitError",
    "SyncResult",
    "__version__",
    "apply_block",
    "check_conflicts",
    "comment_prefix_for",
    "find_config",
    "load_catalog",
    "load_repo_config",
    "managed_note",
    "parse_service",
    "parse_service_list",
    "render_block",
    "resolve_services",
]
