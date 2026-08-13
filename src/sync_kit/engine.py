"""The reconciliation engine: apply services to a working tree."""

from __future__ import annotations

import contextlib
import difflib
import errno
import os
import secrets
import stat
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import ManagedFile, Service, check_conflicts
from .config import builtin_variables, render
from .errors import ConfigError
from .markers import (
    DEFAULT_NAMESPACE,
    apply_block,
    comment_lines,
    comment_prefix_for,
    supports_comments,
)
from .paths import normalize_relative_path, resolve_inside, resolve_repo_root

# Mode-specific wording so `head` on a managed file says whether it is safe to edit.
NOTE_WORDING = {
    "file": "{note}\nDo not edit — every sync run overwrites this file.",
    "init": (
        "{note}\nStarter template, safe to customize. This file is only ever "
        "created, never overwritten."
    ),
}


@dataclass(frozen=True)
class Change:
    """One pending or applied modification."""

    service: str
    path: str
    action: str  # created | updated | deleted
    before: str = ""
    after: str = ""

    def describe(self) -> str:
        return f"{self.action}: {self.path} ({self.service})"

    def diff(self, context: int = 2) -> str:
        """Unified diff of the change, for job logs."""
        label = self.path if self.before else f"{self.path} (new file)"
        return "".join(
            difflib.unified_diff(
                self.before.splitlines(keepends=True),
                self.after.splitlines(keepends=True),
                fromfile=f"a/{label}",
                tofile="/dev/null" if self.action == "deleted" else f"b/{self.path}",
                n=context,
            )
        )


@dataclass(frozen=True)
class FileResult:
    """The reconciliation outcome for one service-managed file."""

    service: str
    path: str
    action: str | None = None


@dataclass
class SyncResult:
    """Outcome of a sync run."""

    changes: list[Change] = field(default_factory=list)
    file_results: list[FileResult] = field(default_factory=list)
    dry_run: bool = False

    @property
    def changed_files(self) -> list[str]:
        return list(dict.fromkeys(change.path for change in self.changes))

    @property
    def changed(self) -> bool:
        return bool(self.changes)


class SyncEngine:
    """Applies a set of services to a repository working tree.

    ``dry_run`` computes the same change set without touching the filesystem,
    which is what powers the drift check.
    """

    def __init__(
        self,
        root: Path,
        dry_run: bool = False,
        variables: dict[str, str] | None = None,
        namespace: str = DEFAULT_NAMESPACE,
        note: str | None = None,
    ) -> None:
        self.root = resolve_repo_root(root)
        self.dry_run = dry_run
        self.namespace = namespace
        self.note = note
        self.variables = builtin_variables(variables)

    def sync(self, services: Iterable[Service]) -> SyncResult:
        services = tuple(services)
        check_conflicts(services)
        result = SyncResult(dry_run=self.dry_run)
        states: dict[str, _FileState] = {}
        target_owners: dict[Path, str] = {}
        for service in services:
            for managed in service.files:
                path = normalize_relative_path(
                    managed.path,
                    key=f"service '{service.name}' path",
                )
                state = states.get(path)
                if state is None:
                    state = self._read_state(
                        path,
                        allow_binary=managed.mode in {"absent", "init"},
                    )
                    owner = target_owners.get(state.target)
                    if owner is not None:
                        raise ConfigError(
                            f"managed paths '{owner}' and '{path}' resolve to the same target"
                        )
                    target_owners[state.target] = path
                    states[path] = state
                change = self._plan_file(service, managed, path, state)
                if change is not None:
                    result.changes.append(change)
                result.file_results.append(
                    FileResult(service=service.name, path=path, action=change.action if change else None)
                )

        encoded: dict[str, bytes] = {}
        for path, state in states.items():
            if not state.changed or not state.exists:
                continue
            try:
                encoded[path] = state.content.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ConfigError(f"managed content must be valid UTF-8: {path}") from exc

        if not self.dry_run:
            for path, state in states.items():
                if state.changed:
                    self._assert_unchanged(path, state)
            for path, state in states.items():
                if not state.changed:
                    continue
                try:
                    self._assert_unchanged(path, state)
                    if state.exists:
                        _atomic_write_bytes(
                            self.root,
                            state.target,
                            encoded[path],
                            mode=(
                                state.mode
                                if state.mode is not None
                                else 0o666
                            ),
                            create=state.original is None,
                        )
                    else:
                        _unlink_file(self.root, state.target)
                except OSError as exc:
                    raise ConfigError(f"failed to update managed path '{path}': {exc}") from exc
        return result

    def _read_state(self, path: str, *, allow_binary: bool) -> _FileState:
        lexical_target = self.root / path
        if lexical_target.is_symlink():
            raise ConfigError(f"managed path must not be a symbolic link: {path}")
        relative_target = Path(path)
        resolved_parent = resolve_inside(
            self.root,
            relative_target.parent.as_posix(),
            key="managed path parent",
        )
        target = resolved_parent / relative_target.name
        current_state = _read_regular_file(
            self.root,
            target,
            path,
            missing_ok=True,
        )
        if current_state is None:
            return _FileState(
                target=target,
                exists=False,
                content="",
                original=None,
                mode=None,
                identity=None,
            )

        raw, metadata = current_state
        try:
            content = raw.decode("utf-8", errors="replace" if allow_binary else "strict")
        except UnicodeDecodeError as exc:
            raise ConfigError(f"managed path must be UTF-8 text: {path}") from exc
        return _FileState(
            target=target,
            exists=True,
            content=content,
            original=raw,
            mode=stat.S_IMODE(metadata.st_mode),
            identity=(metadata.st_dev, metadata.st_ino),
        )

    def _assert_unchanged(self, path: str, state: _FileState) -> None:
        """Fail before committing if another process changed a planned target."""
        if state.target.is_symlink():
            raise ConfigError(f"managed path became a symbolic link during sync: {path}")
        if state.original is None:
            if _read_regular_file(
                self.root,
                state.target,
                path,
                missing_ok=True,
            ) is not None:
                raise ConfigError(f"managed path appeared during sync; retry: {path}")
            return
        current_state = _read_regular_file(
            self.root,
            state.target,
            path,
            missing_ok=True,
        )
        if current_state is None:
            raise ConfigError(f"managed path changed during sync; retry: {path}")
        current, metadata = current_state
        identity = (metadata.st_dev, metadata.st_ino)
        mode = stat.S_IMODE(metadata.st_mode)
        if current != state.original or identity != state.identity or mode != state.mode:
            raise ConfigError(f"managed path changed during sync; retry: {path}")

    def _plan_file(
        self,
        service: Service,
        managed: ManagedFile,
        path: str,
        state: _FileState,
    ) -> Change | None:
        exists = state.exists
        current = state.content

        if managed.mode == "absent":
            if not exists:
                return None
            state.exists = False
            state.content = ""
            state.changed = True
            return Change(service.name, path, "deleted", before=current)

        if managed.mode == "init" and exists:
            return None

        content = render(managed.content, self.variables)

        if managed.mode in ("init", "file"):
            desired = _with_final_newline(self._with_header(managed, content))
        else:
            base = current if exists else self._scaffold(managed)
            desired = apply_block(
                base,
                service.name,
                content,
                managed.comment_prefix or comment_prefix_for(managed.path),
                self.namespace,
                self._note_for(managed),
            )

        if exists and desired == current:
            return None

        state.exists = True
        state.content = desired
        state.changed = True

        return Change(
            service=service.name,
            path=path,
            action="updated" if exists else "created",
            before=current,
            after=desired,
        )

    def _scaffold(self, managed: ManagedFile) -> str:
        """Root structure written once when a block-mode file is created."""
        if not managed.scaffold:
            return ""
        return _with_final_newline(render(managed.scaffold, self.variables))

    def _note_for(self, managed: ManagedFile) -> str | None:
        if not self.note or not supports_comments(managed.path):
            return None
        return render(self.note, self.variables)

    def _with_header(self, managed: ManagedFile, content: str) -> str:
        """Prefix whole-file and init content with the managed note, after any shebang."""
        note = self._note_for(managed)
        if not note:
            return content
        prefix = managed.comment_prefix or comment_prefix_for(managed.path)
        header = "\n".join(comment_lines(NOTE_WORDING[managed.mode].format(note=note), prefix))
        lines = content.splitlines(keepends=True)
        if lines and lines[0].startswith("#!"):
            shebang = lines[0]
            if not shebang.endswith(("\n", "\r")):
                shebang += "\n"
            return shebang + header + "\n" + "".join(lines[1:])
        return f"{header}\n{content}"


def _with_final_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


@dataclass
class _FileState:
    target: Path
    exists: bool
    content: str
    original: bytes | None
    mode: int | None
    identity: tuple[int, int] | None
    changed: bool = False


def _read_regular_file(
    root: Path,
    target: Path,
    path: str,
    *,
    missing_ok: bool = False,
) -> tuple[bytes, os.stat_result] | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    parent_descriptor = -1
    descriptor = -1
    try:
        parent_descriptor, target_name = _open_parent_directory(
            root,
            target,
            create=False,
        )
        descriptor = os.open(target_name, flags, dir_fd=parent_descriptor)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ConfigError(f"managed path is not a regular file: {path}")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read(), metadata
    except FileNotFoundError:
        if missing_ok:
            return None
        raise ConfigError(f"managed path disappeared during sync; retry: {path}") from None
    except OSError as exc:
        raise ConfigError(f"failed to read managed path '{path}': {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def _atomic_write_bytes(
    root: Path,
    target: Path,
    content: bytes,
    *,
    mode: int,
    create: bool,
) -> None:
    parent_descriptor, target_name = _open_parent_directory(root, target, create=True)
    descriptor = -1
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = _open_temporary(
            parent_descriptor,
            target_name,
            mode if create else 0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            if not create:
                os.fchmod(handle.fileno(), mode)
                _copy_access_acl(parent_descriptor, target_name, handle.fileno())
        if create:
            os.link(
                temporary_name,
                target_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        else:
            os.replace(
                temporary_name,
                target_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
            )
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            if temporary_name is not None:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(temporary_name, dir_fd=parent_descriptor)
        finally:
            os.close(parent_descriptor)


def _open_parent_directory(root: Path, target: Path, *, create: bool) -> tuple[int, str]:
    """Open a target's parent beneath ``root`` without following symlinks."""
    try:
        relative_target = target.relative_to(root)
    except ValueError as exc:  # pragma: no cover - guarded by path resolution
        raise ConfigError(f"managed path resolves outside the repository: {target}") from exc

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags)
    try:
        for part in relative_target.parts[:-1]:
            try:
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, 0o777, dir_fd=descriptor)
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, relative_target.name
    except BaseException:
        os.close(descriptor)
        raise


def _open_temporary(
    parent_descriptor: int,
    target_name: str,
    mode: int,
) -> tuple[int, str]:
    """Create a random temporary in an already validated target directory."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    for _ in range(100):
        temporary_name = f".{target_name}.{secrets.token_hex(8)}.tmp"
        try:
            return os.open(temporary_name, flags, mode, dir_fd=parent_descriptor), temporary_name
        except FileExistsError:
            continue
    raise ConfigError(f"failed to allocate temporary file for managed path: {target_name}")


def _copy_access_acl(
    parent_descriptor: int,
    source_name: str,
    destination_descriptor: int,
) -> None:
    """Preserve the source file's POSIX access ACL when the platform supports it."""
    if not all(hasattr(os, name) for name in ("getxattr", "setxattr", "removexattr")):
        return

    source_descriptor = os.open(
        source_name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_descriptor,
    )
    attribute = "system.posix_acl_access"
    unsupported = {errno.ENODATA, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}
    try:
        try:
            value = os.getxattr(source_descriptor, attribute)
        except OSError as exc:
            if exc.errno not in unsupported:
                raise
            try:
                os.removexattr(destination_descriptor, attribute)
            except OSError as remove_exc:
                if remove_exc.errno not in unsupported:
                    raise
        else:
            os.setxattr(destination_descriptor, attribute, value)
    finally:
        os.close(source_descriptor)


def _unlink_file(root: Path, target: Path) -> None:
    parent_descriptor, target_name = _open_parent_directory(root, target, create=False)
    try:
        os.unlink(target_name, dir_fd=parent_descriptor)
    finally:
        os.close(parent_descriptor)
