#!/usr/bin/env python3
"""Drift guard between ``action.yml`` and ``pyproject.toml``.

Run in CI on every PR to catch the class of bugs where someone bumps
metadata in one file and forgets the other. Currently asserts:

  * ``action.yml::author``         == ``pyproject.toml::project.authors[0].name``
  * ``action.yml::description``    <= 125 chars  (defense in depth — MP010
                                                  is enforced by the
                                                  marketplace-kit check
                                                  too, but failing locally
                                                  here gives a faster signal)
  * ``action.yml::runs.using``     == 'composite'
  * ``action.yml::branding.color`` ∈ Marketplace enum
  * ``action.yml::branding.icon``  is non-empty

Pure stdlib (yaml + tomllib). Exits 0 on success, 1 on any drift,
with a human-readable report.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml  # PyYAML is a hard runtime dep of the kit
except ImportError:
    sys.stderr.write("PyYAML missing; install dev deps: pip install -e '.[dev]'\n")
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
ACTION_YML = REPO_ROOT / "action.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"

DESC_MAX = 125  # MP010
BRANDING_COLORS = {
    "white", "yellow", "blue", "green", "orange", "red", "purple", "gray-dark",
}


def _read_pyproject_author(text: str) -> str:
    """Extract `authors[0].name` from a pyproject.toml.

    Avoids a hard dep on tomllib (py311+) or tomli (third-party) for what
    is otherwise a stdlib-only kit. Pyproject's `authors` line is stable:

        authors = [{name = "Blackout Secure"}]
    """
    m = re.search(
        r'^\s*authors\s*=\s*\[\s*\{\s*name\s*=\s*"([^"]+)"',
        text,
        re.MULTILINE,
    )
    return m.group(1).strip() if m else ""


def main() -> int:
    failures: list[str] = []

    action = yaml.safe_load(ACTION_YML.read_text())
    pyproject_text = PYPROJECT.read_text()

    # ----- author -----
    action_author = (action.get("author") or "").strip()
    py_author = _read_pyproject_author(pyproject_text)
    if not action_author:
        failures.append("action.yml: missing top-level `author`")
    elif not py_author:
        failures.append("pyproject.toml: could not find `authors[0].name`")
    elif action_author != py_author:
        failures.append(
            f"author drift: action.yml={action_author!r} "
            f"!= pyproject.toml={py_author!r}"
        )

    # ----- description -----
    action_desc = (action.get("description") or "").strip()
    if not action_desc:
        failures.append("action.yml: missing top-level `description`")
    elif len(action_desc) > DESC_MAX:
        failures.append(
            f"action.yml::description is {len(action_desc)} chars "
            f"(> {DESC_MAX}); Marketplace card view will truncate"
        )

    # ----- runs.using -----
    runs_using = (action.get("runs") or {}).get("using")
    if runs_using != "composite":
        failures.append(f"action.yml::runs.using = {runs_using!r}, expected 'composite'")

    # ----- branding -----
    branding = action.get("branding") or {}
    color = branding.get("color")
    icon = branding.get("icon")
    if color not in BRANDING_COLORS:
        failures.append(
            f"action.yml::branding.color = {color!r}; allowed: {sorted(BRANDING_COLORS)}"
        )
    if not icon:
        failures.append("action.yml::branding.icon is empty")

    # ----- report -----
    if failures:
        print(f"check_action_sync: {len(failures)} drift(s) found:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(
        f"check_action_sync: OK "
        f"(author={action_author!r}, desc={len(action_desc)} chars, "
        f"runs.using={runs_using!r}, branding={color}/{icon})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
