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
import json
import os
import sys
from pathlib import Path

from . import __version__
from .catalog import load_catalog, resolve_services
from .config import (
    find_config,
    load_repo_config,
    managed_note,
    marker_namespace,
    parse_service_list,
    string_map,
)
from .engine import SyncEngine, SyncResult
from .errors import ConfigError, SyncKitError

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_CONFIG = 2

DEFAULT_GLOBAL_CONFIG_PATH = ".github/blackout-secure-managed-file-sync-global-config.json"


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=".", help="Repository root to sync (default: current directory)")
    parser.add_argument(
        "--use-global-config",
        action="store_true",
        help="Enable org/hub-level global config merge (off by default)",
    )
    parser.add_argument(
        "--global-config",
        default=DEFAULT_GLOBAL_CONFIG_PATH,
        help=(
            "Path to org/hub-level config file when --use-global-config is set "
            f"(default: {DEFAULT_GLOBAL_CONFIG_PATH})"
        ),
    )
    parser.add_argument("--config", default=None, help="Path to repo-specific config file (overrides global)")
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
        self.root = Path(args.root).resolve()
        self.config_file = find_config(self.root, args.config)
        self.global_config_file = (
            find_config(self.root, args.global_config)
            if args.use_global_config
            else None
        )
        self.section = load_repo_config(
            config_file=self.config_file,
            global_config_file=self.global_config_file,
        )
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
    with open(output_file, "a", encoding="utf-8") as handle:
        handle.write(f"changed={'true' if result.changed else 'false'}\n")
        handle.write(f"changed_count={len(files)}\n")
        handle.write(f"changed_files_json={json.dumps(files)}\n")
        handle.write("changed_files<<MFS_EOF\n")
        handle.write("\n".join(files) + ("\n" if files else ""))
        handle.write("MFS_EOF\n")


def _print_header(plan: _Plan, mode: str) -> None:
    print(f"bos-managed-file-sync {__version__}")
    print(f"config:    {plan.config_file or '(none — using inputs and defaults)'}")
    print(f"root:      {plan.root}")
    print(f"namespace: {plan.namespace}")
    print(f"services:  {', '.join(service.name for service in plan.services) or '(none)'}")
    print(f"mode:      {mode}")


def _run_sync(plan: _Plan, dry_run: bool, fail_on_drift: bool, show_diff: bool = True) -> int:
    _print_header(plan, "dry-run" if dry_run else "apply")

    if not plan.services:
        print("\nNo services enabled — nothing to do.")
        _write_github_output(SyncResult(dry_run=dry_run))
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
