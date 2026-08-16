"""Path validation shared by config parsing and filesystem reconciliation."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from .errors import ConfigError


def normalize_relative_path(value: Any, *, key: str, allow_current: bool = False) -> str:
    """Return a normalized repo-relative path without traversal or output controls."""
    raw = str(value).strip()
    if not raw or any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise ConfigError(f"{key} must be a non-empty relative path: {value!r}")

    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ConfigError(f"{key} must be a relative path inside the repo: {raw}")

    normalized = path.as_posix()
    if normalized == "." and not allow_current:
        raise ConfigError(f"{key} must name a file inside the repo, not the repo root")
    return normalized


def resolve_inside(root: Path, relative_path: str, *, key: str) -> Path:
    """Resolve a relative path and reject symlinks that escape ``root``."""
    try:
        resolved_root = root.resolve()
        candidate = (resolved_root / relative_path).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ConfigError(f"failed to resolve {key} '{relative_path}': {exc}") from exc
    if not candidate.is_relative_to(resolved_root):
        raise ConfigError(f"{key} resolves outside its allowed root: {relative_path}")
    return candidate


def resolve_repo_root(value: Path | str) -> Path:
    """Resolve and validate the repository root used for reconciliation."""
    try:
        root = Path(value).resolve()
    except (OSError, RuntimeError) as exc:
        raise ConfigError(f"failed to resolve repository root '{value}': {exc}") from exc
    if not root.is_dir():
        raise ConfigError(f"repository root is not a directory: {root}")
    return root


def read_utf8_file_inside(root: Path, relative_path: str, *, key: str) -> str | None:
    """Read a contained regular file without following raced path components."""
    resolved_root = root.resolve()
    normalized_path = normalize_relative_path(relative_path, key=key)
    resolve_inside(resolved_root, normalized_path, key=key)
    relative_candidate = Path(normalized_path)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | no_follow
    descriptor = -1
    try:
        descriptor = os.open(resolved_root, directory_flags)
        for part in relative_candidate.parts[:-1]:
            next_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        file_descriptor = os.open(
            relative_candidate.name,
            os.O_RDONLY | no_follow,
            dir_fd=descriptor,
        )
        with os.fdopen(file_descriptor, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ConfigError(f"{key} is not a regular file: {relative_path}")
            content = handle.read()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ConfigError(f"failed to read {key} '{relative_path}': {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{key} must be UTF-8 text: {relative_path}") from exc
