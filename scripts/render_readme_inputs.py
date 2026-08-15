#!/usr/bin/env python3
"""Render the README Action-inputs and Action-outputs tables from ``action.yml``.

Two modes:

  * ``--check``  — exit 1 with a diff if README is stale (CI mode).
  * ``--write``  — rewrite the README in place (developer mode).

The README must contain matching marker pairs:

    <!-- BEGIN action-inputs -->
    ...table...
    <!-- END action-inputs -->

    <!-- BEGIN action-outputs -->
    ...table...
    <!-- END action-outputs -->

Pure stdlib + PyYAML. No third-party markdown libraries.
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML missing; install dev deps: pip install -e '.[dev]'\n")
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
ACTION_YML = REPO_ROOT / "action.yml"
README = REPO_ROOT / "README.md"

INPUTS_BEGIN = "<!-- BEGIN action-inputs -->"
INPUTS_END = "<!-- END action-inputs -->"
OUTPUTS_BEGIN = "<!-- BEGIN action-outputs -->"
OUTPUTS_END = "<!-- END action-outputs -->"


def _esc(text: str) -> str:
    """Escape pipes so the cell renders correctly in a Markdown table."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _default_cell(default: str | None) -> str:
    if default is None or default == "":
        return "_(none)_"
    # Render GitHub Actions expressions as inline code and leave others quoted.
    if "${{" in default:
        return f"`{default}`"
    return f"`{default}`"


def render_inputs(action: dict) -> str:
    inputs = action.get("inputs") or {}
    lines = [
        "| Input | Default | Description |",
        "| --- | --- | --- |",
    ]
    for name, spec in inputs.items():
        spec = spec or {}
        default = spec.get("default")
        # GitHub Actions auto-converts non-string defaults; coerce for display.
        if isinstance(default, bool):
            default = str(default).lower()
        elif default is not None:
            default = str(default)
        desc = spec.get("description", "")
        lines.append(f"| `{name}` | {_default_cell(default)} | {_esc(desc)} |")
    return "\n".join(lines) + "\n"


def render_outputs(action: dict) -> str:
    outputs = action.get("outputs") or {}
    lines = [
        "| Output | Description |",
        "| --- | --- |",
    ]
    for name, spec in outputs.items():
        spec = spec or {}
        desc = spec.get("description", "")
        lines.append(f"| `{name}` | {_esc(desc)} |")
    return "\n".join(lines) + "\n"


def _replace_block(text: str, begin: str, end: str, body: str) -> str:
    pattern = re.compile(
        re.escape(begin) + r"\n.*?\n" + re.escape(end),
        re.DOTALL,
    )
    if not pattern.search(text):
        sys.stderr.write(
            f"render_readme_inputs: marker pair not found: {begin} / {end}\n"
        )
        sys.exit(2)
    replacement = f"{begin}\n{body.rstrip()}\n{end}"
    return pattern.sub(replacement, text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 if README is stale")
    mode.add_argument("--write", action="store_true", help="rewrite README in place")
    args = parser.parse_args()

    action = yaml.safe_load(ACTION_YML.read_text())
    inputs_body = render_inputs(action)
    outputs_body = render_outputs(action)

    current = README.read_text()
    updated = _replace_block(current, INPUTS_BEGIN, INPUTS_END, inputs_body)
    updated = _replace_block(updated, OUTPUTS_BEGIN, OUTPUTS_END, outputs_body)

    if args.write:
        if updated == current:
            print("render_readme_inputs: already up to date")
            return 0
        README.write_text(updated)
        print("render_readme_inputs: README.md updated")
        return 0

    # --check
    if updated == current:
        print("render_readme_inputs: OK (tables match action.yml)")
        return 0
    diff = difflib.unified_diff(
        current.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile="README.md (current)",
        tofile="README.md (expected from action.yml)",
        n=3,
    )
    sys.stdout.write("".join(diff))
    sys.stderr.write(
        "\nREADME tables are stale. Run: python3 scripts/render_readme_inputs.py --write\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
