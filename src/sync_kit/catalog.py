"""Service registry: what "in sync" means.

Service definitions are centralized in merged config (`managed_file_sync`),
which already includes marketplace + global + repo tiers.

Services are pure data — nothing here is executed, fetched, or evaluated.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_repo_config
from .errors import ConfigError

VALID_MODES = ("block", "file", "init", "absent")

# Modes where two enabled services claiming the same path would fight each other.
EXCLUSIVE_MODES = ("file", "init", "absent")

MAX_BUNDLE_DEPTH = 10


@dataclass(frozen=True)
class ManagedFile:
    """A single file managed by a service."""

    path: str
    content: str
    mode: str
    comment_prefix: str | None = None
    # Written once, before the first block, when a block-mode file is created.
    scaffold: str | None = None


@dataclass(frozen=True)
class Service:
    """A named group of managed files, or a bundle of other services."""

    name: str
    mode: str
    files: tuple[ManagedFile, ...]
    description: str = ""
    includes: tuple[str, ...] = ()


def _read_content(entry: dict[str, Any], base_dirs: Iterable[Path]) -> str:
    """Resolve ``content`` / ``content_lines`` / ``content_file`` on an entry."""
    if "content" in entry:
        content = entry["content"]
        if isinstance(content, list):
            return "\n".join(str(line) for line in content)
        return str(content)
    if "content_lines" in entry:
        return "\n".join(str(line) for line in entry["content_lines"])
    if "content_file" in entry:
        rel = str(entry["content_file"])
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise ConfigError(f"content_file must be a relative path inside the repo: {rel}")
        for base in base_dirs:
            candidate = base / rel
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
        raise ConfigError(f"content_file not found: {rel}")
    raise ConfigError("service file needs one of: content, content_lines, content_file")


def parse_service(name: str, spec: dict[str, Any], base_dirs: Iterable[Path] = ()) -> Service:
    """Turn a raw service definition into a validated :class:`Service`."""
    if not isinstance(spec, dict):
        raise ConfigError(f"service '{name}' must be a JSON object")

    mode = str(spec.get("mode", "block"))
    if mode not in VALID_MODES:
        raise ConfigError(f"service '{name}' has unknown mode '{mode}' (expected one of {VALID_MODES})")

    includes = spec.get("includes")
    if includes is not None:
        if not isinstance(includes, list) or not includes:
            raise ConfigError(f"service '{name}' has an empty or non-list 'includes'")
        if spec.get("files"):
            raise ConfigError(f"service '{name}' must define either 'includes' or 'files', not both")
        return Service(
            name=name,
            mode=mode,
            files=(),
            description=str(spec.get("description", "")),
            includes=tuple(str(item) for item in includes),
        )

    raw_files = spec.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ConfigError(f"service '{name}' must define a non-empty 'files' list")

    base_dirs = tuple(base_dirs)
    files: list[ManagedFile] = []
    for entry in raw_files:
        if not isinstance(entry, dict):
            raise ConfigError(f"service '{name}' has a non-object file entry")
        path = str(entry.get("path", "")).strip()
        if not path:
            raise ConfigError(f"service '{name}' has a file entry without 'path'")
        # Containment check: service definitions must never write outside the repo.
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ConfigError(f"service '{name}' path must stay inside the repo: {path}")
        file_mode = str(entry.get("mode", mode))
        if file_mode not in VALID_MODES:
            raise ConfigError(f"service '{name}' file '{path}' has unknown mode '{file_mode}'")
        scaffold = entry.get("scaffold")
        if scaffold is not None and file_mode != "block":
            raise ConfigError(f"service '{name}' file '{path}': 'scaffold' only applies to block mode")
        if isinstance(scaffold, list):
            scaffold = "\n".join(str(line) for line in scaffold)
        files.append(
            ManagedFile(
                path=path,
                content="" if file_mode == "absent" else _read_content(entry, base_dirs),
                mode=file_mode,
                comment_prefix=entry.get("comment_prefix"),
                scaffold=None if scaffold is None else str(scaffold),
            )
        )

    return Service(
        name=name,
        mode=mode,
        files=tuple(files),
        description=str(spec.get("description", "")),
    )


def load_catalog(
    root: Path,
    section: dict[str, Any] | None = None,
    managed_files_path: str | None = None,
) -> dict[str, Service]:
    """Build the resolved service registry for a repository."""
    base_section = load_repo_config(use_marketplace=True)
    section = section or {}

    if section.get("use_marketplace_config") is False:
        effective_section: dict[str, Any] = dict(section)
    else:
        effective_section = dict(base_section)
        effective_section.update(section)
        merged_defs: dict[str, Any] = {}
        base_defs = base_section.get("service_definitions")
        if isinstance(base_defs, dict):
            merged_defs.update(base_defs)
        override_defs = section.get("service_definitions")
        if isinstance(override_defs, dict):
            merged_defs.update(override_defs)
        if merged_defs:
            effective_section["service_definitions"] = merged_defs

    raw: dict[str, Any] = {}

    path_value = managed_files_path if managed_files_path is not None else effective_section.get("managed_files_path")
    if path_value in (None, ""):
        path_value = ".github/managed-files"
    rel_managed_path = Path(str(path_value))
    if rel_managed_path.is_absolute() or ".." in rel_managed_path.parts:
        raise ConfigError(
            f"managed_files_path must be a relative path inside the repo: {path_value}"
        )
    managed_files_dir = root / rel_managed_path

    # `content_file` sources for repo/global service_definitions come from
    # managed_files_path. Destination is still set explicitly per service via
    # files[].path.
    base_dirs: list[Path] = [managed_files_dir]

    overrides = effective_section.get("service_definitions") or {}
    if not isinstance(overrides, dict):
        raise ConfigError("'service_definitions' must be a JSON object keyed by service name")
    raw.update(overrides)

    return {name: parse_service(name, spec, base_dirs) for name, spec in raw.items()}


def resolve_services(
    catalog: dict[str, Service],
    section: dict[str, Any] | None = None,
    requested: Iterable[str] | None = None,
) -> list[Service]:
    """Resolve enabled service names into ordered :class:`Service` objects."""
    section = section or {}
    if requested:
        names = [str(name) for name in requested]
    else:
        enabled = section.get("services", [])
        if isinstance(enabled, dict):
            names = [str(name) for name, on in enabled.items() if on]
        elif isinstance(enabled, list):
            names = [str(name) for name in enabled]
        else:
            raise ConfigError("'services' must be a list or an object of name -> bool")

    if names in (["*"], ["all"]):
        names = sorted(name for name, service in catalog.items() if not service.includes)

    disabled = {
        *(str(name) for name in section.get("disabled_services", [])),
        *(str(name) for name in section.get("exclude_services", [])),
    }
    resolved: list[Service] = []
    unknown: list[str] = []
    _expand(names, catalog, disabled, resolved, unknown, depth=0)

    if unknown:
        raise ConfigError(
            "unknown service(s): "
            + ", ".join(sorted(unknown))
            + f". Known services: {', '.join(sorted(catalog))}"
        )
    check_conflicts(resolved)
    return resolved


def _expand(
    names: Iterable[str],
    catalog: dict[str, Service],
    disabled: set[str],
    resolved: list[Service],
    unknown: list[str],
    depth: int,
) -> None:
    """Resolve names in order, expanding bundle services into their members."""
    if depth > MAX_BUNDLE_DEPTH:
        raise ConfigError("service 'includes' nested too deeply — check for a cycle")
    for raw_name in names:
        name = raw_name.strip()
        if not name or name in disabled:
            continue
        service = catalog.get(name)
        if service is None:
            unknown.append(name)
        elif service.includes:
            _expand(service.includes, catalog, disabled, resolved, unknown, depth + 1)
        elif service not in resolved:
            resolved.append(service)


def check_conflicts(services: Iterable[Service]) -> None:
    """Reject two enabled services that claim the same whole-file path.

    Co-targeting definitions are legal in a catalog (per-language variants of
    the same file, for example); enabling more than one in a single repo is
    not, because the last one to run would silently win.
    """
    owners: dict[tuple[str, str], str] = {}
    for service in services:
        for managed in service.files:
            if managed.mode not in EXCLUSIVE_MODES:
                continue
            key = (managed.mode, managed.path)
            owner = owners.get(key)
            if owner is not None and owner != service.name:
                raise ConfigError(
                    f"services '{owner}' and '{service.name}' both claim {managed.mode}-mode "
                    f"path '{managed.path}'. Enable at most one of them per repo."
                )
            owners[key] = service.name
