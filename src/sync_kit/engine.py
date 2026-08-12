"""The reconciliation engine: apply services to a working tree."""

from __future__ import annotations

import difflib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import ManagedFile, Service
from .config import builtin_variables, render
from .markers import (
    DEFAULT_NAMESPACE,
    apply_block,
    comment_lines,
    comment_prefix_for,
    supports_comments,
)

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


@dataclass
class SyncResult:
    """Outcome of a sync run."""

    changes: list[Change] = field(default_factory=list)
    dry_run: bool = False

    @property
    def changed_files(self) -> list[str]:
        seen: list[str] = []
        for change in self.changes:
            if change.path not in seen:
                seen.append(change.path)
        return seen

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
        self.root = Path(root).resolve()
        self.dry_run = dry_run
        self.namespace = namespace
        self.note = note
        self.variables = {**builtin_variables(), **(variables or {})}

    def sync(self, services: Iterable[Service]) -> SyncResult:
        result = SyncResult(dry_run=self.dry_run)
        for service in services:
            for managed in service.files:
                change = self._sync_file(service, managed)
                if change is not None:
                    result.changes.append(change)
        return result

    def _sync_file(self, service: Service, managed: ManagedFile) -> Change | None:
        target = self.root / managed.path
        exists = target.is_file()
        current = target.read_text(encoding="utf-8") if exists else ""

        if managed.mode == "absent":
            if not exists:
                return None
            if not self.dry_run:
                target.unlink()
            return Change(service.name, managed.path, "deleted", before=current)

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

        if not self.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(desired, encoding="utf-8")

        return Change(
            service=service.name,
            path=managed.path,
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
            return lines[0] + header + "\n" + "".join(lines[1:])
        return f"{header}\n{content}"


def _with_final_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"
