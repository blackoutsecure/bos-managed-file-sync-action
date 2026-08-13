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
from .catalog import load_catalog, resolve_services
from .config import (
    find_config,
    load_repo_config,
    managed_note,
    marker_namespace,
    parse_service_list,
    string_map,
    sync_direction,
)
from .engine import FileResult, SyncEngine, SyncResult
from .errors import ConfigError, SyncKitError
from .paths import resolve_repo_root

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CONFIG = 2

DEFAULT_GLOBAL_CONFIG_PATH = ".github/blackout-secure-managed-file-sync-global-config.json"


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=".", help="Repository root to sync (default: current directory)")
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
    parser.add_argument("--config", default=None, help="Path to repo-specific config file (overrides global)")
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
    parser.add_argument("--services", default=None, help="Comma separated service list overriding the config")


def _add_sync_arguments(parser: argparse.ArgumentParser) -> None:
    _add_common_arguments(parser)
    parser.add_argument("--no-diff", action="store_true", help="List changed files without unified diffs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bos-sync",
        description="Sync canonical managed files and managed blocks across repositories.",
    )
    parser.add_argument("--version", action="version", version=f"bos-managed-file-sync {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    services = subparsers.add_parser("services", help="List the services in the resolved config")
    _add_common_arguments(services)

    validate = subparsers.add_parser("validate", help="Validate the repo config")
    _add_common_arguments(validate)

    apply_cmd = subparsers.add_parser("apply", help="Reconcile the working tree")
    _add_sync_arguments(apply_cmd)
    apply_cmd.add_argument("--dry-run", action="store_true", help="Report changes without writing files")
    apply_cmd.add_argument("--fail-on-drift", action="store_true", help="Exit non-zero when changes are needed")

    check = subparsers.add_parser("check", help="Drift gate: dry-run that fails when files are out of sync")
    _add_sync_arguments(check)

    return parser


class _Plan:
    """Everything resolved from disk before any file is touched."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.root = resolve_repo_root(args.root)
        self.config_file = find_config(self.root, args.config)
        global_config = self.root / args.global_config
        if args.use_global_config is True:
            self.global_config_file = find_config(self.root, args.global_config)
        elif args.use_global_config is False:
            self.global_config_file = None
        else:
            self.global_config_file = global_config if global_config.is_file() else None
        self.section = load_repo_config(
            config_file=self.config_file,
            global_config_file=self.global_config_file,
            global_config_json=args.global_config_json,
            config_json=args.config_json,
        )
        self.direction = sync_direction(self.section)
        self.catalog = load_catalog(
            root=self.root,
            section=self.section,
            managed_files_path=args.managed_files_path,
            section_is_merged=True,
        )
        self.services = resolve_services(self.catalog, self.section, parse_service_list(args.services))
        self.namespace = marker_namespace(self.section)
        self.note = managed_note(self.section)
        self.variables = string_map(self.section.get("variables"))


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


def _write_github_summary(plan: _Plan, result: SyncResult) -> None:
    """Write an at-a-glance run report when GitHub Actions provides a summary file."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
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
        else "complete"
    )
    marketplace = plan.section.get("marketplace") or {}
    allowlist = marketplace.get("allowlist_paths") or []
    blocked = marketplace.get("blocked_paths") or []
    required = marketplace.get("required_paths") or []
    repo_metadata = marketplace.get("repo_metadata") or {}
    security = plan.section.get("security") or {}
    general = plan.section.get("general") or {}

    review_rows = [
        ("use_marketplace_config", plan.section.get("use_marketplace_config", True)),
        ("security.enable_python_lint", security.get("enable_python_lint")),
        ("security.python_version", security.get("python_version")),
        ("marketplace.enabled", marketplace.get("enabled", False)),
        ("marketplace.allowlist_paths", allowlist),
        ("marketplace.blocked_paths", blocked),
        ("marketplace.required_paths", required),
        ("marketplace.repo_metadata.enable", repo_metadata.get("enable", False)),
        ("marketplace.repo_metadata.homepage", repo_metadata.get("homepage")),
        ("general.action_test.python_versions", general.get("action_test", {}).get("python_versions")),
        ("services", plan.section.get("services") or []),
    ]

    recommendations: list[str] = []
    if plan.section.get("use_marketplace_config") is False:
        recommendations.append("Marketplace defaults are intentionally disabled for this repo; confirm that custom policy is deliberate.")
    else:
        recommendations.append("Marketplace defaults remain enabled; repo policy is inheriting the standard baseline.")
    if security.get("enable_python_lint") is True:
        recommendations.append(f"Python linting is enabled for {security.get('python_version', 'default')}.")
    if repo_metadata.get("enable") is True:
        recommendations.append(f"Repo metadata automation is enabled with homepage {repo_metadata.get('homepage') or '(unspecified)'}.")
    if allowlist:
        recommendations.append(f"Marketplace allowlist is limited to: {serialize(allowlist)}.")
    if blocked:
        recommendations.append(f"Marketplace blocked paths are restricted to: {serialize(blocked)}.")
    if required:
        recommendations.append(f"Required marketplace paths are enforced: {serialize(required)}.")
    if excluded:
        recommendations.append(f"Excluded services are intentionally skipped: {serialize(excluded)}.")
    if disabled:
        recommendations.append(f"Disabled services are explicitly filtered out: {serialize(disabled)}.")
    if not recommendations:
        recommendations.append("No extra policy overrides are configured; the repo is using the default marketplace baseline.")

    action_labels = ["Already compliant"]
    action_labels.extend(["Created", "Updated", "Deleted"])

    visible_actions = [label for label in action_labels if action_counts.get(label, 0)]
    status_counts = {
        "Compliant": len(compliant),
        "Pending": len(pending),
        "Applied": len(applied),
    }
    visible_statuses = [label for label in status_counts if status_counts[label]]

    lines = [
        f"## Managed file sync: {verdict}",
        "",
        "### Results",
        "",
        f"| {' | '.join(visible_statuses)} | Evaluated files | Changed files |",
        f"| {' | '.join(['---:'] * len(visible_statuses))} | ---: | ---: |",
        f"| {' | '.join(str(status_counts[label]) for label in visible_statuses)} | {len(result.file_results)} | {len(result.changed_files)} |",
        "",
        "### Sync status",
        "",
        f"{'No active managed files were evaluated; configured services were excluded or disabled.' if not result.file_results and (excluded or disabled) else 'All managed files are in sync.' if not result.changed else f'Drift detected: {len(result.changed_files)} file(s) would change.' if result.dry_run else f'Applied {len(result.changed_files)} file(s) and updated the repo.'}",
        "",
        "### Resolved configuration",
        "",
        "<pre>",
        f"config: {escaped(plan.config_file or '(none — using inputs and defaults)')}",
        f"root: {escaped(plan.root)}",
        f"direction: {escaped(plan.direction)}",
        f"namespace: {escaped(plan.namespace)}",
        f"services: {escaped(', '.join(service.name for service in plan.services) if plan.services else '(none)')}",
        f"mode: {'dry-run' if result.dry_run else 'apply'}",
        "</pre>",
        "",
    ]

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
        lines.append(f"| <code>{escaped(field)}</code> | <code>{escaped(serialize(value))}</code> |")

    lines.extend([
        "",
        "### Review recommendations",
        "",
    ])
    for recommendation in recommendations:
        lines.append(f"- {recommendation}")

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
    print(f"bos-managed-file-sync {__version__}")
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
        _write_github_summary(plan, result)
        return EXIT_OK

    engine = SyncEngine(
        plan.root,
        dry_run=dry_run,
        variables=plan.variables,
        namespace=plan.namespace,
        note=plan.note,
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
    _write_github_summary(plan, result)

    if fail_on_drift and result.changed:
        print("::error::managed-file-sync detected drift in managed files.", file=sys.stderr)
        return EXIT_DRIFT
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        plan = _Plan(args)

        if args.command == "services":
            for name in sorted(plan.catalog):
                service = plan.catalog[name]
                kind = f"bundle -> {', '.join(service.includes)}" if service.includes else service.mode
                print(f"{name} [{kind}] — {service.description}")
            return EXIT_OK

        if args.command == "validate":
            _print_header(plan, "validate")
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
        print(f"::error::managed-file-sync config error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except SyncKitError as exc:
        print(f"::error::managed-file-sync error: {exc}", file=sys.stderr)
        return EXIT_CONFIG


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
