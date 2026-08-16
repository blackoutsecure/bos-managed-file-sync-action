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

from .config import CONFIG_SECTION, find_config, load_repo_config, marker_identifier
from .errors import ConfigError
from .paths import normalize_relative_path, read_utf8_file_inside, resolve_inside

VALID_MODES = ("block", "file", "init", "update", "absent")

MAX_BUNDLE_DEPTH = 10


@dataclass(frozen=True)
class _ContentRoot:
    root: Path
    relative_path: str


@dataclass(frozen=True)
class ManagedFile:
    """A single file managed by a service."""

    path: str
    content: str
    mode: str
    comment_prefix: str | None = None
    marker_namespace: str | None = None
    # None inherits the section-level managed note; False suppresses it.
    include_managed_note: bool | None = None
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


def _read_content(
    entry: dict[str, Any],
    base_dirs: Iterable[Path | _ContentRoot],
) -> str:
    """Resolve ``content`` / ``content_lines`` / ``content_file`` on an entry."""
    sources = [key for key in ("content", "content_lines", "content_file") if key in entry]
    if len(sources) != 1:
        raise ConfigError("service file needs exactly one of: content, content_lines, content_file")
    if "content" in entry:
        content = entry["content"]
        if isinstance(content, list):
            return "\n".join(str(line) for line in content)
        return str(content)
    if "content_lines" in entry:
        content_lines = entry["content_lines"]
        if not isinstance(content_lines, list):
            raise ConfigError("service file 'content_lines' must be a JSON array")
        return "\n".join(str(line) for line in content_lines)

    rel = normalize_relative_path(entry["content_file"], key="content_file")
    for base in base_dirs:
        if isinstance(base, _ContentRoot):
            anchored_path = (Path(base.relative_path) / rel).as_posix()
            content = read_utf8_file_inside(
                base.root,
                anchored_path,
                key="content_file",
            )
        else:
            content = read_utf8_file_inside(base, rel, key="content_file")
        if content is not None:
            return content
    raise ConfigError(f"content_file not found: {rel}")


def parse_service(
    name: str,
    spec: dict[str, Any],
    base_dirs: Iterable[Path | _ContentRoot] = (),
) -> Service:
    """Turn a raw service definition into a validated :class:`Service`."""
    name = marker_identifier(name, "service name")
    if not isinstance(spec, dict):
        raise ConfigError(f"service '{name}' must be a JSON object")

    mode = str(spec.get("mode", "block"))
    if mode not in VALID_MODES:
        raise ConfigError(
            f"service '{name}' has unknown mode '{mode}' (expected one of {VALID_MODES})"
        )

    includes = spec.get("includes")
    if includes is not None:
        if not isinstance(includes, list) or not includes:
            raise ConfigError(f"service '{name}' has an empty or non-list 'includes'")
        if "files" in spec:
            raise ConfigError(
                f"service '{name}' must define either 'includes' or 'files', not both"
            )
        return Service(
            name=name,
            mode=mode,
            files=(),
            description=str(spec.get("description", "")),
            includes=tuple(
                marker_identifier(item, f"service '{name}' include") for item in includes
            ),
        )

    raw_files = spec.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ConfigError(f"service '{name}' must define a non-empty 'files' list")

    base_dirs = tuple(base_dirs)
    files: list[ManagedFile] = []
    for entry in raw_files:
        if not isinstance(entry, dict):
            raise ConfigError(f"service '{name}' has a non-object file entry")
        raw_path = entry.get("path", "")
        if not str(raw_path).strip():
            raise ConfigError(f"service '{name}' has a file entry without 'path'")
        path = normalize_relative_path(raw_path, key=f"service '{name}' path")
        file_mode = str(entry.get("mode", mode))
        if file_mode not in VALID_MODES:
            raise ConfigError(f"service '{name}' file '{path}' has unknown mode '{file_mode}'")
        scaffold = entry.get("scaffold")
        if scaffold is not None and file_mode != "block":
            raise ConfigError(
                f"service '{name}' file '{path}': 'scaffold' only applies to block mode"
            )
        if isinstance(scaffold, list):
            scaffold = "\n".join(str(line) for line in scaffold)
        comment_prefix = entry.get("comment_prefix")
        if comment_prefix is not None:
            comment_prefix = str(comment_prefix)
            if any(ord(character) < 32 or ord(character) == 127 for character in comment_prefix):
                raise ConfigError(f"service '{name}' file '{path}' has an invalid comment_prefix")
        marker_namespace = entry.get("marker_namespace")
        if marker_namespace is not None:
            marker_namespace = marker_identifier(
                marker_namespace,
                f"service '{name}' file '{path}' marker_namespace",
            )
        include_managed_note = entry.get("include_managed_note")
        if include_managed_note is not None and not isinstance(include_managed_note, bool):
            raise ConfigError(
                f"service '{name}' file '{path}' has invalid include_managed_note"
            )
        files.append(
            ManagedFile(
                path=path,
                content="" if file_mode == "absent" else _read_content(entry, base_dirs),
                mode=file_mode,
                comment_prefix=comment_prefix,
                marker_namespace=marker_namespace,
                include_managed_note=include_managed_note,
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
    section_is_merged: bool = False,
) -> dict[str, Service]:
    """Build the resolved service registry for a repository."""
    if section_is_merged:
        effective_section = dict(section or {})
    else:
        config_file = find_config(root)
        effective_section = load_repo_config(config_file=config_file, use_marketplace=True)
        if section:
            if section.get("use_marketplace_config") is False:
                effective_section = dict(section)
            else:
                base_defs = effective_section.get("service_definitions")
                override_defs = section.get("service_definitions")
                effective_section = {**effective_section, **section}
                if isinstance(base_defs, dict) and isinstance(override_defs, dict):
                    effective_section["service_definitions"] = {**base_defs, **override_defs}

    raw: dict[str, Any] = {}

    path_value = (
        managed_files_path
        if managed_files_path is not None
        else effective_section.get("managed_files_path")
    )
    if path_value in (None, ""):
        path_value = ".github/managed-files"
    rel_managed_path = normalize_relative_path(
        path_value,
        key="managed_files_path",
        allow_current=True,
    )
    resolved_root = root.resolve()
    managed_files_dir = resolve_inside(
        resolved_root,
        rel_managed_path,
        key="managed_files_path",
    )
    anchored_managed_path = managed_files_dir.relative_to(resolved_root).as_posix()

    # `content_file` sources for repo/global service_definitions come from
    # managed_files_path. Destination is still set explicitly per service via
    # files[].path.
    base_dirs: list[Path | _ContentRoot] = [_ContentRoot(resolved_root, anchored_managed_path)]

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
            invalid = [name for name, on in enabled.items() if not isinstance(on, bool)]
            if invalid:
                raise ConfigError("'services' object values must be true or false")
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
    resolved_names: set[str] = set()
    unknown: list[str] = []
    _expand(
        names,
        catalog,
        disabled,
        resolved,
        resolved_names,
        unknown,
        depth=0,
    )

    if unknown:
        missing_paths = ", ".join(
            f"{CONFIG_SECTION}.service_definitions.{name}" for name in sorted(set(unknown))
        )
        available = ", ".join(sorted(catalog)) or "(none)"
        raise ConfigError(
            f"missing service definition schema(s): {missing_paths}. "
            f"Each name selected by '{CONFIG_SECTION}.services', the workflow "
            f"'services' input, or a service 'includes' entry must have a matching "
            f"object under '{CONFIG_SECTION}.service_definitions'. "
            f"Available service definitions: {available}"
        )
    check_conflicts(resolved)
    return resolved


def _expand(
    names: Iterable[str],
    catalog: dict[str, Service],
    disabled: set[str],
    resolved: list[Service],
    resolved_names: set[str],
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
        name = marker_identifier(name, "service name")
        service = catalog.get(name)
        if service is None:
            unknown.append(name)
        elif service.includes:
            _expand(
                service.includes,
                catalog,
                disabled,
                resolved,
                resolved_names,
                unknown,
                depth + 1,
            )
        elif name not in resolved_names:
            resolved.append(service)
            resolved_names.add(name)


def check_conflicts(services: Iterable[Service]) -> None:
    """Reject enabled services with ambiguous ownership of a managed path.

    Distinct block services may safely share a file because their markers are
    independent. Every other combination is order-dependent and rejected.
    """
    owners: dict[str, tuple[str, str]] = {}
    claims: set[tuple[str, str]] = set()
    for service in services:
        for managed in service.files:
            path = normalize_relative_path(
                managed.path,
                key=f"service '{service.name}' path",
            )
            claim = (service.name, path)
            if claim in claims:
                raise ConfigError(f"service '{service.name}' claims path '{path}' more than once")
            claims.add(claim)
            owner = owners.get(path)
            if owner is None:
                owners[path] = (service.name, managed.mode)
                continue

            owner_name, owner_mode = owner
            if owner_mode == managed.mode == "block":
                continue
            raise ConfigError(
                f"services '{owner_name}' ({owner_mode}) and '{service.name}' "
                f"({managed.mode}) both claim path '{path}'"
            )
