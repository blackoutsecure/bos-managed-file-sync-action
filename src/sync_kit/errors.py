"""Exception hierarchy for the managed-file sync kit."""

from __future__ import annotations


class SyncKitError(Exception):
    """Base class for every error raised by the kit."""


class ConfigError(SyncKitError):
    """Repo config or service definition is invalid."""


class MarkerError(SyncKitError):
    """A managed block in a target file is malformed."""
