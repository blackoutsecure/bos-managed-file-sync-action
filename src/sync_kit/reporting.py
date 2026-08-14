"""Structured failure findings and GitHub Actions error reports."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError, MarkerError

_SCHEMA_PATH = re.compile(r"managed_file_sync\.service_definitions\.[A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class ErrorFinding:
    """A deterministic assessment of one managed-file-sync failure."""

    rule_id: str
    category: str
    severity: str
    location: str
    evidence: str
    remediation: str
    confidence: str
    source: str = "Blackout Secure deterministic rules"

    def ai_payload(self) -> dict[str, str]:
        """Return the allowlisted fields that may be sent to an AI provider."""
        return {
            "category": self.category,
            "error_text": self.evidence,
            "location": self.location,
            "deterministic_remediation": self.remediation,
        }


@dataclass(frozen=True)
class AssistedRemediation:
    """Optional advisory guidance returned by an AI provider."""

    recommendation: str
    rationale: str
    confidence: str
    source: str


@dataclass(frozen=True)
class FailureContext:
    """Non-secret invocation metadata available even when config loading fails."""

    command: str
    mode: str
    repository_root: str
    repository_config: str
    global_config: str
    service_selection: str
    config_sources: tuple[str, ...]
    package_version: str


def assess_error(error: Exception) -> ErrorFinding:
    """Classify an exception into a stable rule and deterministic remediation."""
    message = str(error).strip() or type(error).__name__
    lower = message.lower()
    location = _error_location(message)

    if "missing service definition schema(s)" in lower:
        return _finding(
            "MFS-CFG-004",
            "Missing service definition schema",
            location,
            message,
            "Add an object for every listed schema path under "
            "`managed_file_sync.service_definitions`, or remove the undefined name "
            "from `services`, the workflow `services` input, or a bundle `includes` list. "
            "Then run `bos-sync validate` before retrying the sync.",
        )
    if "content_file not found" in lower:
        return _finding(
            "MFS-CFG-005",
            "Managed content template not found",
            location,
            message,
            "Create the referenced `content_file` below the configured "
            "`managed_files_path`, or correct the relative template path in the service definition.",
        )
    if "invalid json" in lower:
        return _finding(
            "MFS-CFG-001",
            "Invalid configuration JSON",
            location,
            message,
            "Correct the JSON syntax at the reported location and validate the document with a "
            "JSON parser before rerunning `bos-sync validate`.",
        )
    if "config file not found" in lower or lower.startswith("file not found:"):
        return _finding(
            "MFS-CFG-002",
            "Configuration file not found",
            location,
            message,
            "Create the requested configuration file, correct the configured path, or disable the "
            "required config tier when it is intentionally absent.",
        )
    if isinstance(error, MarkerError) or "marker namespace" in lower or "managed block" in lower:
        return _finding(
            "MFS-MARKER-001",
            "Managed block ownership or marker error",
            location,
            message,
            "Repair the reported start/end marker pair or configure the intended `marker_namespace`. "
            "Enable `take_over_managed_files` only when replacing the competing owner is deliberate.",
        )
    if (
        "both claim path" in lower
        or "claims path" in lower
        or "resolve to the same target" in lower
    ):
        return _finding(
            "MFS-CFG-006",
            "Conflicting managed path ownership",
            location,
            message,
            "Assign the path to one service, or use distinct marker namespaces when multiple "
            "block-mode services intentionally share a file.",
        )
    if "during sync; retry" in lower:
        return _finding(
            "MFS-FS-002",
            "Concurrent filesystem change",
            location,
            message,
            "Stop the process modifying the managed path, restore a stable working tree, and rerun "
            "the sync. The action did not overwrite the concurrently changed target.",
        )
    if (
        "outside the repository" in lower
        or "outside its allowed root" in lower
        or "must be a relative path" in lower
        or "symbolic link" in lower
        or "must name a file inside the repo" in lower
    ):
        return _finding(
            "MFS-SAFE-001",
            "Unsafe managed path",
            location,
            message,
            "Use a regular, repository-relative path with no `..` traversal or symlink target. "
            "Keep managed templates inside `managed_files_path`.",
        )
    if (
        "failed to read" in lower
        or "failed to update" in lower
        or "failed to write" in lower
        or "failed to allocate temporary file" in lower
        or "must be utf-8" in lower
        or "must be valid utf-8" in lower
        or "not a regular file" in lower
    ):
        return _finding(
            "MFS-FS-001",
            "Managed file I/O error",
            location,
            message,
            "Verify that the path is a regular UTF-8 file and that the runner can read its parents "
            "and write the target, then retry with an unchanged working tree.",
        )
    if isinstance(error, ConfigError):
        return _finding(
            "MFS-CFG-003",
            "Invalid managed-file-sync schema",
            location,
            message,
            "Correct the reported field in `managed_file_sync` or its service definition, then run "
            "`bos-sync validate` to verify the merged configuration.",
        )
    return _finding(
        "MFS-RUN-000",
        "Managed-file-sync runtime error",
        location,
        message,
        "Review the error evidence and runner filesystem state, correct the underlying condition, "
        "and rerun the action. Escalate with the report rule and package version if it persists.",
        confidence="Medium (deterministic)",
    )


def render_failure_summary(
    finding: ErrorFinding,
    context: FailureContext,
    *,
    ai_status: str,
    assisted: AssistedRemediation | None = None,
) -> str:
    """Render a self-contained failure report in the standard audit layout."""
    sources = ", ".join(context.config_sources) or "No config source resolved"
    verdict = (
        "Critical configuration error"
        if finding.rule_id.startswith("MFS-CFG-")
        else "Critical managed-file sync error"
    )
    lines = [
        "# Blackout Secure Managed File Sync Report - failure",
        "",
        "**Provided by [Blackout Secure](https://blackoutsecure.app)**",
        "",
        "## Navigation",
        "",
        "- [Executive summary](#executive-summary)",
        "- [Configuration used](#configuration-used)",
        "- [Errors requiring attention](#errors-requiring-attention)",
        "- [Recommendations](#recommendations)",
        "- [Scope and methodology](#scope-and-methodology)",
        "",
        "## Executive summary",
        "",
        "| Stage | Result | Details |",
        "| --- | --- | --- |",
        f"| {_cell(context.command)} | failure | {_cell(finding.category)} |",
        "",
        f"**Verdict:** {verdict}",
        "",
        "Managed-file reconciliation stopped before completion. Do not infer that the working tree "
        "is compliant from this run.",
        "",
        "## Configuration used",
        "",
        "| Setting | Value | What it means |",
        "| --- | --- | --- |",
        f"| Command | {_cell(context.command)} | CLI operation requested by the action. |",
        f"| Mode | {_cell(context.mode)} | Whether file writes were permitted. |",
        f"| Repository root | {_cell(context.repository_root)} | Root used for path containment. |",
        f"| Repository config | {_cell(context.repository_config)} | Requested repository policy source. |",
        f"| Global config | {_cell(context.global_config)} | Requested organization policy source. |",
        f"| Service selection | {_cell(context.service_selection)} | CLI override or merged config selection. |",
        f"| Config cascade | {_cell(sources)} | Sources requested in precedence order. |",
        f"| Package version | {_cell(context.package_version)} | Managed-file-sync version producing this report. |",
        f"| AI-assisted remediation | {_cell(ai_status)} | Advisory only; deterministic guidance remains authoritative. |",
        "",
        "## Errors requiring attention",
        "",
        "| Rule | Severity | Category | Location | Evidence | Recommended remediation | Confidence | Source |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        f"| `{_cell(finding.rule_id)}` | {_cell(finding.severity)} | "
        f"{_cell(finding.category)} | {_cell(finding.location)} | {_cell(finding.evidence)} | "
        f"{_cell(finding.remediation)} | {_cell(finding.confidence)} | {_cell(finding.source)} |",
        "",
        "## Recommendations",
        "",
        "### Blackout Secure Recommended Remediation",
        "",
        finding.remediation,
        "",
        f"**Confidence:** {finding.confidence}  ",
        f"**Source:** {finding.source}",
        "",
        "### AI-assisted remediation",
        "",
    ]
    if assisted is None:
        lines.append(f"_Not used: {ai_status}._")
    else:
        lines.extend(
            [
                assisted.recommendation,
                "",
                f"**Rationale:** {assisted.rationale}",
                "",
                f"**Confidence:** {assisted.confidence}  ",
                f"**Source:** {assisted.source}",
            ]
        )
    lines.extend(
        [
            "",
            "## Scope and methodology",
            "",
            "- The deterministic rule is selected from the exception type and error text emitted by "
            "the managed-file-sync parser, catalog, marker, path-safety, or filesystem boundary.",
            "- AI is optional and cannot change the finding, severity, exit code, or deterministic "
            "remediation.",
            "- When AI is used, only error category, error text, location, and deterministic remediation "
            "are sent. Config contents, managed-file contents, diffs, and credentials are not sent.",
            "- Summary-write and AI-provider failures never replace the original action error.",
            "",
        ]
    )
    return "\n".join(lines)


def append_failure_summary(path: str, report: str) -> bool:
    """Append a report without allowing summary I/O to mask the original failure."""
    try:
        with Path(path).open("a", encoding="utf-8") as handle:
            handle.write(report)
    except OSError:
        return False
    return True


def _finding(
    rule_id: str,
    category: str,
    location: str,
    evidence: str,
    remediation: str,
    *,
    confidence: str = "High (deterministic)",
) -> ErrorFinding:
    return ErrorFinding(
        rule_id=rule_id,
        category=category,
        severity="Critical",
        location=location,
        evidence=evidence,
        remediation=remediation,
        confidence=confidence,
    )


def _error_location(message: str) -> str:
    schema_paths = sorted(set(_SCHEMA_PATH.findall(message)))
    if schema_paths:
        return ", ".join(schema_paths)
    for pattern in (
        r"content_file not found:\s*([^.;]+)",
        r"invalid JSON in\s+(.+?):\s+line\s+\d+",
        r"config file not found:\s*(.+)$",
        r"file not found:\s*(.+)$",
        r"managed path ['\"]?([^'\";]+)['\"]?",
        r"service ['\"]([^'\"]+)['\"]",
    ):
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "Configuration or runner context"


def _cell(value: object) -> str:
    escaped = html.escape(str(value), quote=True)
    return escaped.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")
