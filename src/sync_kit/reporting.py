"""Structured failure findings and GitHub Actions error reports."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError, MarkerError
from .paths import normalize_relative_path

_SCHEMA_PATH = re.compile(r"managed_file_sync\.service_definitions\.[A-Za-z0-9_.-]+")
_ARTIFACT_NAME_FORBIDDEN = frozenset('\\/:*?"<>|\r\n')
REPORT_LABELS = {
    "pass": "Pass",
    "warn": "Warning",
    "fail": "High",
    "skip": "Not Assessed",
}
REPORT_MEANINGS = {
    "pass": "Control satisfied.",
    "warn": "Advisory drift; review recommended.",
    "fail": "Required control failed and must be corrected.",
    "skip": "Not evaluated on this run; coverage cannot be inferred.",
}


@dataclass(frozen=True)
class ReportingSettings:
    """Normalized organization-wide report policy."""

    enable_job_summary: bool = True
    enable_annotations: bool = True
    enable_html: bool = True
    enable_pdf: bool = False
    html_path: str = "blackout-secure-report.html"
    pdf_path: str = "blackout-secure-report.pdf"
    artifact_name: str = "blackout-secure-audit-report"
    title_prefix: str = "Blackout Secure"
    fail_on: str = "fail"


def reporting_settings(section: dict[str, Any]) -> ReportingSettings:
    """Read ``organization.reporting`` using the automation hub defaults."""
    organization = section.get("organization")
    if organization is None:
        organization = {}
    if not isinstance(organization, dict):
        raise ConfigError("'organization' must be a JSON object")
    reporting = organization.get("reporting")
    if reporting is None:
        reporting = {}
    if not isinstance(reporting, dict):
        raise ConfigError("'organization.reporting' must be a JSON object")

    fail_on = _reporting_text(reporting, "fail_on", "fail").lower()
    if fail_on not in {"fail", "warn", "never"}:
        raise ConfigError(
            "'organization.reporting.fail_on' must be 'fail', 'warn', or 'never'"
        )

    html_path = normalize_relative_path(
        _reporting_text(reporting, "html_path", "blackout-secure-report.html"),
        key="organization.reporting.html_path",
    )
    pdf_path = normalize_relative_path(
        _reporting_text(reporting, "pdf_path", "blackout-secure-report.pdf"),
        key="organization.reporting.pdf_path",
    )
    artifact_name = _reporting_text(
        reporting,
        "artifact_name",
        "blackout-secure-audit-report",
    )
    if any(character in _ARTIFACT_NAME_FORBIDDEN for character in artifact_name):
        raise ConfigError(
            "'organization.reporting.artifact_name' contains a character GitHub artifacts do not allow"
        )

    return ReportingSettings(
        enable_job_summary=_reporting_bool(reporting, "enable_job_summary", True),
        enable_annotations=_reporting_bool(reporting, "enable_annotations", True),
        enable_html=_reporting_bool(reporting, "enable_html", True),
        enable_pdf=_reporting_bool(reporting, "enable_pdf", False),
        html_path=html_path,
        pdf_path=pdf_path,
        artifact_name=artifact_name,
        title_prefix=_reporting_text(reporting, "title_prefix", "Blackout Secure"),
        fail_on=fail_on,
    )


def _reporting_bool(reporting: dict[str, Any], key: str, default: bool) -> bool:
    value = reporting.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ConfigError(f"'organization.reporting.{key}' must be true or false")


def _reporting_text(reporting: dict[str, Any], key: str, default: str) -> str:
    value = reporting.get(key)
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"'organization.reporting.{key}' must be a non-empty string")
    return value.strip()


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
    if "organization.reporting" in lower or lower.startswith(
        "'organization' must be a json object"
    ):
        return _finding(
            "MFS-CFG-007",
            "Invalid organization reporting policy",
            location,
            message,
            "Correct the reported field under `organization.reporting`, then run "
            "`bos-sync validate` before retrying. Reporting paths must be safe, "
            "repository-relative paths.",
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
    settings: ReportingSettings | None = None,
) -> str:
    """Render a self-contained failure report in the standard audit layout."""
    settings = settings or ReportingSettings()
    sources = ", ".join(context.config_sources) or "No config source resolved"
    verdict = (
        "High configuration error"
        if finding.rule_id.startswith("MFS-CFG-")
        else "High managed-file sync error"
    )
    severity_label = REPORT_LABELS[finding.severity]
    lines = [
        f"# {_cell(settings.title_prefix)} Managed File Sync Report",
        "",
        "**Provided by [Blackout Secure](https://blackoutsecure.app)**",
        "",
        "> This open-source report provides operational guidance and does not replace "
        "professional security, compliance, or legal advice.",
        "",
        "## Executive summary",
        "",
        "| Stage | Status | Report label | Details |",
        "| --- | --- | --- | --- |",
        f"| {_cell(context.command)} | {finding.severity} | {severity_label} | "
        f"{_cell(finding.category)} |",
        "",
        "| Pass | Warning | High | Not Assessed | Total |",
        "| ---: | ---: | ---: | ---: | ---: |",
        "| 0 | 0 | 1 | 0 | 1 |",
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
        "## Recommended Actions",
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
            "## Detailed Findings",
            "",
            "### Error requiring attention",
            "",
            "| Rule | Status | Severity | Category | Location | Evidence | Recommended remediation | Confidence | Source |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            f"| `{_cell(finding.rule_id)}` | {_cell(finding.severity)} | "
            f"{_cell(severity_label)} | {_cell(finding.category)} | "
            f"{_cell(finding.location)} | {_cell(finding.evidence)} | "
            f"{_cell(finding.remediation)} | {_cell(finding.confidence)} | "
            f"{_cell(finding.source)} |",
            "",
            "### Scope and methodology",
            "",
            "- The deterministic rule is selected from the exception type and error text emitted by "
            "the managed-file-sync parser, catalog, marker, path-safety, or filesystem boundary.",
            "- AI is optional and cannot change the finding, severity, exit code, or deterministic "
            "remediation.",
            "- When AI is used, only error category, error text, location, and deterministic remediation "
            "are sent. Config contents, managed-file contents, diffs, and credentials are not sent.",
            "- Summary-write and AI-provider failures never replace the original action error.",
            f"- Report provenance: `bos-managed-file-sync` {_cell(context.package_version)}; "
            f"finding source: {_cell(finding.source)}.",
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
        severity="fail",
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
        r"'(organization(?:\.reporting(?:\.[A-Za-z0-9_.-]+)?)?)'",
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
