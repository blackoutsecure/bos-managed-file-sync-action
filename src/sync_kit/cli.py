"""Command line interface for the managed-file sync kit.

Subcommands:

    services   list every service in the resolved config
    validate   parse the repo config and report the enabled services
    apply      reconcile the working tree against the enabled services
    check      dry-run drift gate (``apply --dry-run --fail-on-drift``)

Exit codes: ``0`` in sync, ``1`` drift detected, ``2`` config error.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys

from . import __version__
from .ai import AISettings, detect_provider, recommend_error, summarize
from .catalog import apply_file_patches, load_catalog, resolve_services
from .config import (
    MARKETPLACE_CONFIG_FILE,
    ai_settings,
    cleanup_duplicate_lines,
    find_config,
    load_companion_config,
    load_repo_config,
    managed_note,
    marker_namespace,
    parse_service_list,
    string_map,
    sync_direction,
    take_over_managed_files,
)
from .engine import FileResult, SyncEngine, SyncResult
from .errors import ConfigError, SyncKitError
from .metadata import package_metadata
from .paths import resolve_repo_root
from .reporting import (
    REPORT_LABELS,
    REPORT_MEANINGS,
    AssistedRemediation,
    FailureContext,
    ReportingSettings,
    append_failure_summary,
    assess_error,
    render_failure_summary,
    reporting_settings,
)

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CONFIG = 2

DEFAULT_GLOBAL_CONFIG_PATH = ".github/blackout-secure-managed-file-sync-global-config.json"


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root", default=".", help="Repository root to sync (default: current directory)"
    )
    global_config = parser.add_mutually_exclusive_group()
    global_config.add_argument(
        "--use-global-config",
        action="store_true",
        dest="use_global_config",
        help="Require and merge the org/hub-level global config",
    )
    global_config.add_argument(
        "--no-global-config",
        action="store_false",
        dest="use_global_config",
        help="Disable automatic org/hub-level global config discovery",
    )
    parser.set_defaults(use_global_config=None)
    parser.add_argument(
        "--global-config",
        default=DEFAULT_GLOBAL_CONFIG_PATH,
        help=(
            "Org/hub-level config path, loaded automatically when present "
            f"(default: {DEFAULT_GLOBAL_CONFIG_PATH})"
        ),
    )
    parser.add_argument(
        "--config", default=None, help="Path to repo-specific config file (overrides global)"
    )
    marketplace_config = parser.add_mutually_exclusive_group()
    marketplace_config.add_argument(
        "--use-marketplace-config",
        action="store_true",
        dest="use_marketplace_config",
        help="Apply the bundled marketplace baseline config first (default).",
    )
    marketplace_config.add_argument(
        "--no-marketplace-config",
        action="store_false",
        dest="use_marketplace_config",
        help="Skip the bundled marketplace baseline; rely on global/repo config only.",
    )
    parser.set_defaults(use_marketplace_config=True)
    parser.add_argument(
        "--global-config-json",
        default=None,
        help="Inline JSON object to merge into the global config tier before repo config",
    )
    parser.add_argument(
        "--config-json",
        default=None,
        help="Inline JSON object to merge as the highest-priority config tier",
    )
    parser.add_argument(
        "--managed-files-path",
        default=None,
        help="Relative path to managed file templates directory (default: .github/managed-files)",
    )
    parser.add_argument(
        "--services", default=None, help="Comma separated service list overriding the config"
    )


def _add_sync_arguments(parser: argparse.ArgumentParser) -> None:
    _add_common_arguments(parser)
    parser.add_argument(
        "--no-diff", action="store_true", help="List changed files without unified diffs"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bos-sync",
        description="Sync canonical managed files and managed blocks across repositories.",
    )
    parser.add_argument(
        "--version", action="version", version=f"bos-managed-file-sync {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    services = subparsers.add_parser("services", help="List the services in the resolved config")
    _add_common_arguments(services)

    validate = subparsers.add_parser("validate", help="Validate the repo config")
    _add_common_arguments(validate)

    apply_cmd = subparsers.add_parser("apply", help="Reconcile the working tree")
    _add_sync_arguments(apply_cmd)
    apply_cmd.add_argument(
        "--dry-run", action="store_true", help="Report changes without writing files"
    )
    apply_cmd.add_argument(
        "--fail-on-drift", action="store_true", help="Exit non-zero when changes are needed"
    )

    check = subparsers.add_parser(
        "check", help="Drift gate: dry-run that fails when files are out of sync"
    )
    _add_sync_arguments(check)

    return parser


class _Plan:
    """Everything resolved from disk before any file is touched."""

    def __init__(self, args: argparse.Namespace) -> None:
        # Package identity is resolved before config so it stays available
        # even when repo policy is absent, overridden, or fails to load.
        self.package = package_metadata()
        self.root = resolve_repo_root(args.root)
        self.config_file = find_config(self.root, args.config)
        global_config = self.root / args.global_config
        if args.use_global_config is True:
            self.global_config_file = find_config(self.root, args.global_config)
        elif args.use_global_config is False:
            self.global_config_file = None
        else:
            self.global_config_file = global_config if global_config.is_file() else None
        self.ignored_metadata_keys: list[str] = []
        self.marketplace_applied: list[bool] = []
        self.section = load_repo_config(
            config_file=self.config_file,
            global_config_file=self.global_config_file,
            use_marketplace=args.use_marketplace_config,
            global_config_json=args.global_config_json,
            config_json=args.config_json,
            ignored_metadata_keys=self.ignored_metadata_keys,
            marketplace_applied=self.marketplace_applied,
        )
        self.source_paths = self._source_paths(args)
        self.config_source = self._config_source()
        self.reporting = reporting_settings(self.section)
        self.direction = sync_direction(self.section)
        self.ai = ai_settings(self.section)
        self.catalog = load_catalog(
            root=self.root,
            section=self.section,
            managed_files_path=args.managed_files_path,
            section_is_merged=True,
        )
        self.catalog = apply_file_patches(self.catalog, self.section.get("file_patches"))
        self.services = resolve_services(
            self.catalog, self.section, parse_service_list(args.services)
        )
        self.namespace = marker_namespace(self.section)
        self.take_over_managed_files = take_over_managed_files(self.section)
        self.cleanup_duplicate_lines = cleanup_duplicate_lines(self.section)
        self.note = managed_note(self.section)
        self.variables = string_map(self.section.get("variables"))

    def _source_paths(self, args: argparse.Namespace) -> tuple[str, ...]:
        """Applied config tiers, in precedence order."""
        sources: list[str] = []
        if self.marketplace_applied and self.marketplace_applied[0]:
            sources.append(f"{MARKETPLACE_CONFIG_FILE} (bundled)")
        if self.global_config_file:
            sources.append(str(self.global_config_file))
        if args.global_config_json:
            sources.append("--global-config-json (inline)")
        if self.config_file:
            sources.append(str(self.config_file))
        if args.config_json:
            sources.append("--config-json (inline)")
        return tuple(sources)

    def _config_source(self) -> str:
        """The highest-precedence config file, for the `{{config_source}}` variable."""
        for candidate in (self.config_file, self.global_config_file):
            if candidate is None:
                continue
            try:
                return candidate.relative_to(self.root).as_posix()
            except ValueError:
                return str(candidate)
        return MARKETPLACE_CONFIG_FILE


def _failure_ai_settings(
    args: argparse.Namespace,
    plan: _Plan | None,
) -> tuple[AISettings | None, str | None]:
    """Resolve AI policy independently when plan construction did not finish."""
    if plan is not None:
        return plan.ai, None
    try:
        root = resolve_repo_root(args.root)
        config_file = find_config(root, args.config)
        global_candidate = root / args.global_config
        if args.use_global_config is True:
            global_config_file = find_config(root, args.global_config)
        elif args.use_global_config is False:
            global_config_file = None
        else:
            global_config_file = global_candidate if global_candidate.is_file() else None
        section = load_repo_config(
            config_file=config_file,
            global_config_file=global_config_file,
            use_marketplace=args.use_marketplace_config,
            global_config_json=args.global_config_json,
            config_json=args.config_json,
        )
        return ai_settings(section), None
    except SyncKitError:
        return None, "AI policy could not be safely resolved"


def _failure_context(args: argparse.Namespace, plan: _Plan | None) -> FailureContext:
    """Build non-secret report context from the completed plan or CLI inputs."""
    if args.use_global_config is True:
        global_config = f"{args.global_config} (required)"
    elif args.use_global_config is False:
        global_config = "disabled"
    else:
        global_config = f"{args.global_config} (automatic)"
    mode = "dry-run" if getattr(args, "dry_run", False) or args.command == "check" else args.command
    config_sources = (
        plan.source_paths
        if plan is not None
        else (
            f"{MARKETPLACE_CONFIG_FILE} (bundled)",
            global_config,
            *(("--global-config-json (inline)",) if args.global_config_json else ()),
            args.config or "repository config (automatic discovery)",
            *(("--config-json (inline)",) if args.config_json else ()),
        )
    )
    package = plan.package if plan is not None else package_metadata()
    return FailureContext(
        command=args.command,
        mode=mode,
        repository_root=str(plan.root if plan is not None else args.root),
        repository_config=str(
            plan.config_file
            if plan is not None and plan.config_file
            else args.config or "automatic discovery"
        ),
        global_config=str(
            plan.global_config_file
            if plan is not None and plan.global_config_file
            else global_config
        ),
        service_selection=args.services or "merged configuration",
        config_sources=tuple(str(source) for source in config_sources),
        package_version=str(package.get("version", "unknown")),
    )


def _failure_reporting_settings(
    args: argparse.Namespace,
    plan: _Plan | None,
) -> ReportingSettings:
    """Resolve report policy even when the main plan did not finish."""
    if plan is not None:
        return plan.reporting
    try:
        root = resolve_repo_root(args.root)
        config_file = find_config(root, args.config)
        global_candidate = root / args.global_config
        if args.use_global_config is True:
            global_config_file = find_config(root, args.global_config)
        elif args.use_global_config is False:
            global_config_file = None
        else:
            global_config_file = global_candidate if global_candidate.is_file() else None
        organization = load_companion_config(
            "organization",
            config_file=config_file,
            global_config_file=global_config_file,
            global_config_json=args.global_config_json,
            config_json=args.config_json,
        )
        return reporting_settings({"organization": organization})
    except SyncKitError:
        return ReportingSettings()


def _write_failure_report(
    args: argparse.Namespace,
    error: SyncKitError,
    plan: _Plan | None,
    report_settings: ReportingSettings | None = None,
) -> None:
    """Write a best-effort deterministic report, optionally enriched by AI."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    report_settings = report_settings or _failure_reporting_settings(args, plan)
    if not summary_file or not report_settings.enable_job_summary:
        return
    try:
        finding = assess_error(error)
        ai_config, policy_error = _failure_ai_settings(args, plan)
        assisted = None
        if ai_config is None:
            ai_status = f"not attempted; deterministic fallback ({policy_error})"
        elif not ai_config.enable_ai_error_remediation:
            ai_status = "disabled by policy"
        else:
            provider = detect_provider(ai_config.ai_error_remediation_provider)
            if provider is None:
                ai_status = (
                    "unavailable; deterministic fallback (no eligible provider or credential)"
                )
            else:
                recommendation = recommend_error(finding.ai_payload(), provider)
                if recommendation is None:
                    ai_status = f"unavailable ({provider.name}); deterministic fallback"
                else:
                    ai_status = (
                        f"generated by {provider.name} ({provider.model or 'default model'})"
                    )
                    assisted = AssistedRemediation(
                        recommendation=recommendation.recommendation,
                        rationale=recommendation.rationale,
                        confidence=f"{recommendation.confidence} (AI-assessed)",
                        source=f"{provider.name} / {provider.model or 'provider default'}",
                    )
        report = render_failure_summary(
            finding,
            _failure_context(args, plan),
            ai_status=ai_status,
            assisted=assisted,
            settings=report_settings,
        )
        append_failure_summary(summary_file, report)
    except Exception:
        # Reporting is advisory and must never replace the original sync error.
        return


def _write_github_output(result: SyncResult) -> None:
    """Emit action outputs when running inside GitHub Actions."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        return
    files = result.changed_files
    delimiter = "MFS_EOF"
    while delimiter in files:
        delimiter += "_"
    try:
        with open(output_file, "a", encoding="utf-8") as handle:
            handle.write(f"changed={'true' if result.changed else 'false'}\n")
            handle.write(f"changed_count={len(files)}\n")
            handle.write(f"changed_files_json={json.dumps(files)}\n")
            handle.write(f"changed_files<<{delimiter}\n")
            handle.write("\n".join(files) + ("\n" if files else ""))
            handle.write(f"{delimiter}\n")
    except OSError as exc:
        raise ConfigError(f"failed to write GitHub outputs to '{output_file}': {exc}") from exc


def _local_drift_summary(result: SyncResult) -> str:
    """Deterministic drift narrative — always available, never a network call."""
    if not result.changed:
        return "All managed files are in sync."
    per_service: dict[str, int] = {}
    for item in result.file_results:
        if item.action:
            per_service[item.service] = per_service.get(item.service, 0) + 1
    detail = ", ".join(f"{service} ({count})" for service, count in sorted(per_service.items()))
    verb = "would change" if result.dry_run else "changed"
    return f"{len(result.changed_files)} file(s) {verb} across: {detail}."


def _drift_summary(plan: _Plan, result: SyncResult) -> tuple[str, str]:
    """Return the drift summary and its source (provider name or ``local``).

    Only drift metadata (path, service, action) is ever sent to a provider, and
    any failure degrades to the deterministic local summary.
    """
    local = _local_drift_summary(result) if plan.ai.local_heuristic_fallback else ""
    if not plan.ai.enable_ai_drift_summary or not result.changed:
        return local, "local"

    provider = detect_provider(plan.ai.ai_drift_summary_provider)
    if provider is None:
        return local, "local"

    changes = [
        {"path": item.path, "service": item.service, "action": item.action or ""}
        for item in result.file_results
        if item.action
    ]
    text = summarize(changes, provider)
    if not text:
        return local, "local (provider unavailable)"
    return text, provider.name


def _write_github_summary(
    plan: _Plan,
    result: SyncResult,
    *,
    fail_on_drift: bool,
) -> None:
    """Write an at-a-glance run report when GitHub Actions provides a summary file."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file or not plan.reporting.enable_job_summary:
        return

    pending = [item for item in result.file_results if result.dry_run and item.action]
    compliant = [item for item in result.file_results if item.action is None]
    applied = [item for item in result.file_results if not result.dry_run and item.action]
    service_results: dict[str, list[FileResult]] = {}
    for item in result.file_results:
        service_results.setdefault(item.service, []).append(item)

    def escaped(value: object) -> str:
        return html.escape(str(value), quote=True)

    def serialize(value: object) -> str:
        if value is None:
            return "(none)"
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(item) for item in value) if value else "(none)"
        return str(value)

    def action_label(action: str | None) -> str:
        if action is None:
            return "Already compliant"
        return action.capitalize()

    action_counts: dict[str, int] = {
        "Already compliant": 0,
        "Created": 0,
        "Updated": 0,
        "Deleted": 0,
    }
    for item in result.file_results:
        label = action_label(item.action)
        action_counts[label] = action_counts.get(label, 0) + 1

    excluded = plan.section.get("exclude_services") or []
    disabled = plan.section.get("disabled_services") or []
    configured_services = plan.section.get("services") or []
    if isinstance(configured_services, dict):
        requested_services = [name for name, enabled in configured_services.items() if enabled]
    elif isinstance(configured_services, list):
        requested_services = [str(name) for name in configured_services]
    else:
        requested_services = []
    verdict = (
        "changes pending"
        if pending
        else "filtered"
        if not result.file_results and (excluded or disabled)
        else "not assessed"
        if not result.file_results
        else "complete"
    )
    marketplace = plan.section.get("marketplace") or {}
    allowlist = marketplace.get("allowlist_paths") or []
    blocked = marketplace.get("blocked_paths") or []
    required = marketplace.get("required_paths") or []
    repo_metadata = marketplace.get("repo_metadata") or {}
    security = plan.section.get("security") or {}
    general = plan.section.get("general") or {}
    action_test = general.get("action_test") or {}
    toolchain = plan.section.get("recommended_toolchain") or {}
    recommended_python = toolchain.get("python") or {}
    recommended_dependencies = toolchain.get("dependencies") or {}

    review_rows = [
        ("use_marketplace_config", bool(plan.marketplace_applied and plan.marketplace_applied[0])),
        ("take_over_managed_files", plan.take_over_managed_files),
        ("cleanup_duplicate_lines", plan.cleanup_duplicate_lines),
        ("recommended_toolchain.advisory", toolchain.get("advisory")),
        ("recommended_toolchain.python.requires", recommended_python.get("requires")),
        ("recommended_toolchain.python.default_version", recommended_python.get("default_version")),
        ("recommended_toolchain.python.tested_versions", recommended_python.get("tested_versions")),
        ("recommended_toolchain.dependencies.build", recommended_dependencies.get("build")),
        ("recommended_toolchain.dependencies.runtime", recommended_dependencies.get("runtime")),
        (
            "recommended_toolchain.dependencies.development",
            recommended_dependencies.get("development"),
        ),
        ("security.enable_python_lint", security.get("enable_python_lint")),
        ("security.python_version", security.get("python_version")),
        ("security.python_packages", security.get("python_packages")),
        ("marketplace.enabled", marketplace.get("enabled", False)),
        ("marketplace.allowlist_paths", allowlist),
        ("marketplace.blocked_paths", blocked),
        ("marketplace.required_paths", required),
        ("marketplace.repo_metadata.enable", repo_metadata.get("enable", False)),
        ("marketplace.repo_metadata.homepage", repo_metadata.get("homepage")),
        ("general.action_test.python_versions", action_test.get("python_versions")),
        ("general.action_test.os_matrix", action_test.get("os_matrix")),
        ("general.action_test.python_packages", action_test.get("python_packages")),
        ("general.action_test.pytest_args", action_test.get("pytest_args")),
        ("services", plan.section.get("services") or []),
    ]

    recommendations: list[str] = []
    if not (plan.marketplace_applied and plan.marketplace_applied[0]):
        recommendations.append(
            "Marketplace defaults are intentionally disabled for this repo; confirm that custom policy is deliberate."
        )
    else:
        recommendations.append(
            "Marketplace defaults remain enabled; repo policy is inheriting the standard baseline."
        )
    if security.get("enable_python_lint") is True:
        recommendations.append(
            f"Python linting is enabled for {security.get('python_version', 'default')}."
        )
    if toolchain.get("advisory") is True and recommended_python:
        recommendations.append(
            f"Recommended Python is {recommended_python.get('default_version', 'unspecified')} "
            f"({recommended_python.get('requires', 'version requirement unspecified')}); tested versions: "
            f"{serialize(recommended_python.get('tested_versions') or [])}."
        )
    if toolchain.get("advisory") is True and recommended_dependencies:
        runtime_dependencies = recommended_dependencies.get("runtime") or []
        development_dependencies = recommended_dependencies.get("development") or []
        recommendations.append(
            "Recommended dependency policy: "
            f"runtime {serialize(runtime_dependencies)}; development {serialize(development_dependencies)}."
        )
    if repo_metadata.get("enable") is True:
        recommendations.append(
            f"Repo metadata automation is enabled with homepage {repo_metadata.get('homepage') or '(unspecified)'}."
        )
    if allowlist:
        recommendations.append(f"Marketplace allowlist is limited to: {serialize(allowlist)}.")
    if blocked:
        recommendations.append(
            f"Marketplace blocked paths are restricted to: {serialize(blocked)}."
        )
    if required:
        recommendations.append(f"Required marketplace paths are enforced: {serialize(required)}.")
    if excluded:
        recommendations.append(
            f"Excluded services are intentionally skipped: {serialize(excluded)}."
        )
    if disabled:
        recommendations.append(
            f"Disabled services are explicitly filtered out: {serialize(disabled)}."
        )
    if plan.take_over_managed_files:
        recommendations.append(
            "Managed-file takeover is enabled; competing block sections may be removed during apply."
        )
    else:
        recommendations.append(
            "Managed-file takeover is disabled; competing block namespaces fail safely and require explicit ownership configuration."
        )
    if plan.cleanup_duplicate_lines:
        recommendations.append(
            "Duplicate-line cleanup is enabled; lines outside a managed block that duplicate its content are removed."
        )
    else:
        recommendations.append(
            "Duplicate-line cleanup is disabled; lines outside a managed block are never touched, even if they duplicate its content."
        )
    if not recommendations:
        recommendations.append(
            "No extra policy overrides are configured; the repo is using the default marketplace baseline."
        )

    action_labels = ["Already compliant"]
    action_labels.extend(["Created", "Updated", "Deleted"])

    visible_actions = [label for label in action_labels if action_counts.get(label, 0)]
    status_counts = {
        "Compliant": len(compliant),
        "Pending": len(pending),
        "Applied": len(applied),
    }
    visible_statuses = [label for label in status_counts if status_counts[label]]
    if not visible_statuses:
        status_counts["Not Assessed"] = 1
        visible_statuses = ["Not Assessed"]

    report_status = (
        "skip"
        if not result.file_results
        else "fail"
        if result.changed and fail_on_drift
        else "warn"
        if pending
        else "pass"
    )
    drift_text, drift_source = _drift_summary(plan, result)

    lines = [
        f"# {escaped(plan.reporting.title_prefix)} Managed File Sync Report",
        "",
        "**Provided by [Blackout Secure](https://blackoutsecure.app)**",
        "",
        "## Executive summary",
        "",
        f"### Managed file sync: {verdict}",
        "",
        "| Status | Report label | Count | Meaning |",
        "| --- | --- | ---: | --- |",
        f"| {report_status} | {REPORT_LABELS[report_status]} | 1 | "
        f"{REPORT_MEANINGS[report_status]} |",
        "",
        "### Package",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Name | <code>{escaped(plan.package['name'])}</code> |",
        f"| Version | <code>{escaped(plan.package['version'])}</code> |",
        f"| Author | <code>{escaped(plan.package['author'])}</code> |",
        f"| Description | {escaped(plan.package['description'])} |",
        f"| Website | [{escaped(plan.package['website'])}]({escaped(plan.package['website'])}) |",
        f"| Repository | [{escaped(plan.package['repository'])}]({escaped(plan.package['repository'])}) |",
        f"| Documentation | [{escaped(plan.package['documentation'])}]({escaped(plan.package['documentation'])}) |",
        f"| Issues | [{escaped(plan.package['issues'])}]({escaped(plan.package['issues'])}) |",
        f"| Releases | [{escaped(plan.package['releases'])}]({escaped(plan.package['releases'])}) |",
        f"| Marketplace | [{escaped(plan.package['marketplace'])}]({escaped(plan.package['marketplace'])}) |",
        f"| Support | [{escaped(plan.package['support_email'])}](mailto:{escaped(plan.package['support_email'])}) |",
        f"| License | <code>{escaped(plan.package['license'])}</code> |",
        f"| Copyright | {escaped(plan.package['copyright'])} |",
        "",
        "### Results",
        "",
        f"| {' | '.join(visible_statuses)} | Evaluated files | Changed files |",
        f"| {' | '.join(['---:'] * len(visible_statuses))} | ---: | ---: |",
        f"| {' | '.join(str(status_counts[label]) for label in visible_statuses)} | {len(result.file_results)} | {len(result.changed_files)} |",
        "",
        "### Sync status",
        "",
        f"{'No active managed files were evaluated; configured services were excluded or disabled.' if not result.file_results and (excluded or disabled) else 'No active managed files were evaluated; compliance was not assessed.' if not result.file_results else 'All managed files are in sync.' if not result.changed else f'Drift detected: {len(result.changed_files)} file(s) would change.' if result.dry_run else f'Applied {len(result.changed_files)} file(s) and updated the repo.'}",
        "",
    ]

    if drift_text:
        deterministic_drift = drift_source.startswith("local")
        drift_confidence = (
            "High (deterministic)" if deterministic_drift else "Medium (AI-generated advisory)"
        )
        drift_provenance = (
            "Blackout Secure deterministic rules"
            if deterministic_drift
            else f"{drift_source} / {detect_provider(plan.ai.ai_drift_summary_provider).model}"
        )
        lines.extend(
            [
                f"### Drift summary ({escaped(drift_source)})",
                "",
                escaped(drift_text),
                "",
                f"**Confidence:** {escaped(drift_confidence)}  ",
                f"**Source:** {escaped(drift_provenance)}",
                "",
            ]
        )

    lines.extend(
        [
            "## Configuration used",
            "",
            "### Resolved configuration",
            "",
            "<pre>",
            f"config: {escaped(plan.config_file or '(none — using inputs and defaults)')}",
            f"root: {escaped(plan.root)}",
            f"direction: {escaped(plan.direction)}",
            f"namespace: {escaped(plan.namespace)}",
            f"take_over_managed_files: {'true' if plan.take_over_managed_files else 'false'}",
            f"cleanup_duplicate_lines: {'true' if plan.cleanup_duplicate_lines else 'false'}",
            f"services: {escaped(', '.join(service.name for service in plan.services) if plan.services else '(none)')}",
            f"mode: {'dry-run' if result.dry_run else 'apply'}",
            f"config cascade: {escaped(serialize(list(plan.source_paths)))}",
            "</pre>",
            "",
        ]
    )

    if plan.ignored_metadata_keys:
        lines.extend(
            [
                "### Ignored config keys",
                "",
                "Package identity is owned by the installed package, not by config. "
                f"These reserved keys were ignored: <code>{escaped(serialize(plan.ignored_metadata_keys))}</code>.",
                "",
            ]
        )

    lines.extend(
        [
            "",
            "### Service selection",
            "",
            "| State | Services |",
            "| --- | --- |",
            f"| Requested | <code>{escaped(serialize(requested_services))}</code> |",
            f"| Resolved | <code>{escaped(serialize([service.name for service in plan.services]))}</code> |",
            f"| Excluded | <code>{escaped(serialize(excluded))}</code> |",
            f"| Disabled | <code>{escaped(serialize(disabled))}</code> |",
            "",
            "### Configuration",
            "",
            "| Setting | Value |",
            "| --- | --- |",
            f"| Repository root | <code>{escaped(plan.root)}</code> |",
            f"| Repository config | <code>{escaped(plan.config_file or '(none)')}</code> |",
            f"| Global config | <code>{escaped(plan.global_config_file or '(none)')}</code> |",
            f"| Direction | <code>{escaped(plan.direction)}</code> |",
            f"| Marker namespace | <code>{escaped(plan.namespace)}</code> |",
            f"| Take over managed files | <code>{'enabled' if plan.take_over_managed_files else 'disabled'}</code> |",
            f"| Duplicate-line cleanup | <code>{'enabled' if plan.cleanup_duplicate_lines else 'disabled'}</code> |",
            f"| Allowlist paths | <code>{escaped(serialize(allowlist))}</code> |",
            f"| Blocked paths | <code>{escaped(serialize(blocked))}</code> |",
            f"| Required paths | <code>{escaped(serialize(required))}</code> |",
            f"| Repo metadata | <code>{escaped('enabled' if repo_metadata.get('enable', False) else 'disabled')}</code> |",
            f"| Mode | {'dry-run' if result.dry_run else 'apply'} |",
            "",
            "### Full config review",
            "",
            "| Field | Value |",
            "| --- | --- |",
        ]
    )
    for field, value in review_rows:
        lines.append(
            f"| <code>{escaped(field)}</code> | <code>{escaped(serialize(value))}</code> |"
        )

    block_rows = [
        (service.name, managed.path, managed.mode, managed.marker_namespace or plan.namespace)
        for service in plan.services
        for managed in service.files
        if managed.mode == "block"
    ]
    if block_rows:
        lines.extend(
            [
                "",
                "### Block policy",
                "",
                "| Service | File | Mode | Namespace | Takeover |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for service, path, mode, namespace in block_rows:
            lines.append(
                f"| <code>{escaped(service)}</code> | <code>{escaped(path)}</code> | "
                f"<code>{escaped(mode)}</code> | <code>{escaped(namespace)}</code> | "
                f"{'enabled' if plan.take_over_managed_files else 'disabled'} |"
            )

    lines.extend(
        [
            "",
            "## Recommended Actions",
            "",
            "### Review recommendations",
            "",
        ]
    )
    for recommendation in recommendations:
        lines.append(f"- {escaped(recommendation)}")

    lines.extend(
        [
            "",
            "## Detailed Findings",
            "",
        ]
    )

    if visible_actions:
        lines.extend(
            [
                "### Action breakdown",
                "",
                "| Action | Count |",
                "| --- | ---: |",
            ]
        )
        for label in visible_actions:
            lines.append(f"| {label} | {action_counts.get(label, 0)} |")

    lines.extend(
        [
            "",
            "### By service",
            "",
            f"| Service | {' | '.join(visible_statuses)} | Changed |",
            f"| --- | {' | '.join(['---:'] * len(visible_statuses))} | ---: |",
        ]
    )
    for service, items in service_results.items():
        pending_items = sum(result.dry_run and item.action is not None for item in items)
        compliant_items = sum(item.action is None for item in items)
        applied_items = sum(not result.dry_run and item.action is not None for item in items)
        service_status_counts = {
            "Compliant": compliant_items,
            "Pending": pending_items,
            "Applied": applied_items,
        }
        changes = sum(item.action is not None for item in items)
        lines.append(
            f"| <code>{escaped(service)}</code> | "
            f"{' | '.join(str(service_status_counts[label]) for label in visible_statuses)} | {changes} |"
        )
    lines.append(
        f"| **Total** | "
        f"{' | '.join(str(status_counts[label]) for label in visible_statuses)} | "
        f"{len(result.changed_files)} |"
    )

    lines.extend(
        [
            "",
            "### File results",
            "",
            "| Status | File | Service | Result |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in result.file_results:
        if item.action is None:
            status = "Compliant"
        elif result.dry_run:
            status = "Pending"
        else:
            status = "Applied"
        lines.append(
            f"| {status} | <code>{escaped(item.path)}</code> | "
            f"<code>{escaped(item.service)}</code> | {action_label(item.action)} |"
        )

    try:
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError as exc:
        raise ConfigError(f"failed to write GitHub summary to '{summary_file}': {exc}") from exc


def _print_header(plan: _Plan, mode: str) -> None:
    print(f"{plan.package['name']} {plan.package['version']}")
    print(f"config:    {plan.config_file or '(none — using inputs and defaults)'}")
    print(f"root:      {plan.root}")
    print(f"direction: {plan.direction}")
    print(f"namespace: {plan.namespace}")
    print(f"services:  {', '.join(service.name for service in plan.services) or '(none)'}")
    print(f"mode:      {mode}")


def _run_sync(plan: _Plan, dry_run: bool, fail_on_drift: bool, show_diff: bool = True) -> int:
    _print_header(plan, "dry-run" if dry_run else "apply")

    if not plan.services:
        print("\nNo services enabled — nothing to do.")
        result = SyncResult(dry_run=dry_run)
        _write_github_output(result)
        _write_github_summary(plan, result, fail_on_drift=fail_on_drift)
        return EXIT_OK

    engine = SyncEngine(
        plan.root,
        dry_run=dry_run,
        variables=plan.variables,
        namespace=plan.namespace,
        note=plan.note,
        take_over_managed_files=plan.take_over_managed_files,
        cleanup_duplicate_lines=plan.cleanup_duplicate_lines,
        config_source=plan.config_source,
    )
    result = engine.sync(plan.services)

    if result.changed:
        print(f"\n{len(result.changed_files)} file(s) {'would change' if dry_run else 'changed'}:")
        for change in result.changes:
            print(f"  - {change.describe()}")
            if show_diff:
                # Indented so the diff reads as a sub-block of its file in job logs.
                for line in change.diff().splitlines():
                    print(f"      {line}")
    else:
        print("\nAll managed files are in sync.")

    _write_github_output(result)
    _write_github_summary(plan, result, fail_on_drift=fail_on_drift)

    if fail_on_drift and result.changed:
        _emit_error(
            "managed-file-sync detected drift in managed files.",
            annotations=plan.reporting.enable_annotations,
        )
        return EXIT_DRIFT
    if dry_run and result.changed:
        _emit_warning(
            "managed-file-sync detected advisory drift.",
            annotations=plan.reporting.enable_annotations,
        )
    return EXIT_OK


def _emit_diagnostic(message: str, *, level: str, annotations: bool) -> None:
    """Write an escaped GitHub annotation or a plain stderr message."""
    if annotations:
        annotation = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::{level}::{annotation}", file=sys.stderr)
        return
    print(message, file=sys.stderr)


def _emit_error(message: str, *, annotations: bool) -> None:
    _emit_diagnostic(message, level="error", annotations=annotations)


def _emit_warning(message: str, *, annotations: bool) -> None:
    _emit_diagnostic(message, level="warning", annotations=annotations)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan: _Plan | None = None

    try:
        plan = _Plan(args)

        if args.command == "services":
            for name in sorted(plan.catalog):
                service = plan.catalog[name]
                kind = (
                    f"bundle -> {', '.join(service.includes)}" if service.includes else service.mode
                )
                print(f"{name} [{kind}] — {service.description}")
            return EXIT_OK

        if args.command == "validate":
            print("Package metadata:")
            print(f"  name:        {plan.package['name']}")
            print(f"  version:     {plan.package['version']}")
            print(f"  author:      {plan.package['author']}")
            print(f"  description: {plan.package['description']}")
            print(f"  website:     {plan.package['website']}")
            print(f"  repository:  {plan.package['repository']}")
            print(f"  docs:        {plan.package['documentation']}")
            print(f"  issues:      {plan.package['issues']}")
            print(f"  releases:    {plan.package['releases']}")
            print(f"  marketplace: {plan.package['marketplace']}")
            print(f"  support:     {plan.package['support_email']}")
            print(f"  license:     {plan.package['license']}")
            print(f"  copyright:   {plan.package['copyright']}")
            print("Config cascade:")
            for source in plan.source_paths or ("(none — using inputs and defaults)",):
                print(f"  - {source}")
            if plan.ignored_metadata_keys:
                print(
                    "Ignored reserved package metadata keys: "
                    + ", ".join(plan.ignored_metadata_keys)
                )
            print()
            _print_header(plan, "validate")
            print(
                "ai:        "
                f"{'enabled' if plan.ai.enable_ai_drift_summary else 'disabled'} "
                f"(provider: {plan.ai.ai_drift_summary_provider})"
            )
            print("\nConfig is valid.")
            return EXIT_OK

        if args.command == "check":
            return _run_sync(plan, dry_run=True, fail_on_drift=True, show_diff=not args.no_diff)

        return _run_sync(
            plan,
            dry_run=args.dry_run,
            fail_on_drift=args.fail_on_drift,
            show_diff=not args.no_diff,
        )

    except ConfigError as exc:
        report_settings = _failure_reporting_settings(args, plan)
        _emit_error(
            f"managed-file-sync config error: {exc}",
            annotations=report_settings.enable_annotations,
        )
        _write_failure_report(args, exc, plan, report_settings)
        return EXIT_CONFIG
    except SyncKitError as exc:
        report_settings = _failure_reporting_settings(args, plan)
        _emit_error(
            f"managed-file-sync error: {exc}",
            annotations=report_settings.enable_annotations,
        )
        _write_failure_report(args, exc, plan, report_settings)
        return EXIT_CONFIG


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
