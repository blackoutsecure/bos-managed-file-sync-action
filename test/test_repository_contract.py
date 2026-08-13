"""Repository-level contracts shared with bos-automation-hub."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from sync_kit import __version__
from sync_kit.catalog import load_catalog, resolve_services
from sync_kit.config import load_repo_config

ROOT = Path(__file__).resolve().parents[1]
GITHUB = ROOT / ".github"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _yaml_scalar(document: str, key: str, *, indent: int = 0) -> str:
    prefix = " " * indent
    matches = re.findall(
        rf"^{re.escape(prefix + key)}:\s*(?:'([^']*)'|\"([^\"]*)\"|([^\s#]+))\s*$",
        document,
        re.MULTILINE,
    )
    assert len(matches) == 1, f"expected exactly one {key!r} scalar at indent {indent}"
    return next(value for value in matches[0] if value)


def test_action_metadata_matches_package_metadata():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    author_match = re.search(
        r'^\s*authors\s*=\s*\[\s*\{\s*name\s*=\s*"([^"]+)"',
        pyproject,
        re.MULTILINE,
    )
    description_match = re.search(
        r"^description:\s*>-\s*\n((?:  \S.*(?:\n|$))+)",
        action,
        re.MULTILINE,
    )

    assert author_match is not None
    assert description_match is not None
    description = " ".join(line.strip() for line in description_match.group(1).splitlines())
    assert _yaml_scalar(action, "author") == author_match.group(1).strip()
    assert 0 < len(description) <= 125
    assert _yaml_scalar(action, "using", indent=2) == "composite"
    assert _yaml_scalar(action, "color", indent=2) in {
        "white",
        "yellow",
        "blue",
        "green",
        "orange",
        "red",
        "purple",
        "gray-dark",
    }
    assert _yaml_scalar(action, "icon", indent=2)


def test_managed_file_config_disables_duplicate_self_management():
    repo_path = GITHUB / "bos-universal-config.json"
    section = load_repo_config(config_file=repo_path)
    registry = load_catalog(ROOT, section, section_is_merged=True)
    resolved = resolve_services(registry, section)

    assert section == {
        "direction": "source-to-destination",
        "variables": {"fallback_default_runner": "ubuntu-latest"},
        "use_marketplace_config": False,
    }
    assert resolved == []


def test_universal_marketplace_publication_contract():
    config = _json(GITHUB / "bos-universal-config.json")
    marketplace = config["marketplace"]

    assert "source_branch" not in marketplace
    assert marketplace["target_branch"] == "main"
    assert marketplace["include_dependabot_config"] is True
    assert "include_github_metadata" not in marketplace
    assert {
        ".github/dependabot.yml",
        "action.yml",
        "src",
        "README.md",
        "LICENSE",
        "NOTICE",
    } <= set(marketplace["required_paths"])
    assert ".gitignore" not in marketplace["allowlist_paths"]
    assert "test/**" not in marketplace["allowlist_paths"]
    assert "pyproject.toml" not in marketplace["allowlist_paths"]
    assert "scripts/" not in marketplace["allowlist_paths"]
    assert {"pyproject.toml", "scripts/", "test/"} <= set(marketplace["blocked_paths"])
    assert config["general"] == {
        "action_test": {"python_versions": ["3.10", "3.11", "3.12"]}
    }
    assert config["managed_file_sync"] == {
        "direction": "source-to-destination",
        "use_marketplace_config": False,
    }


def test_composite_action_runs_isolated_bundled_source_without_installing():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")

    assert 'python3 -I "${GITHUB_ACTION_PATH}/src/sync_kit/_bootstrap.py" apply' in action
    assert "PYTHONPATH=" not in action
    assert "pip install" not in action
    assert "python3 -m pip" not in action


def test_isolated_bootstrap_ignores_consumer_sync_kit_package(tmp_path):
    shadow_package = tmp_path / "sync_kit"
    shadow_package.mkdir()
    (shadow_package / "__init__.py").write_text(
        "raise RuntimeError('consumer package imported')\n",
        encoding="utf-8",
    )
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "src/sync_kit/_bootstrap.py"),
            "--version",
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == f"bos-managed-file-sync {__version__}"


def test_managed_files_path_input_defers_to_merged_config():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    managed_files_input = action.split("  managed_files_path:", 1)[1].split(
        "  workload_arch:", 1
    )[0]

    assert "default: ''" in managed_files_input


def test_action_auto_discovers_global_config_with_explicit_controls():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    global_config_input = action.split("  use_global_config:", 1)[1].split(
        "  global_config_path:", 1
    )[0]

    assert "default: 'auto'" in global_config_input
    assert 'args=(--root . --global-config "${MFS_GLOBAL_CONFIG_PATH}")' in action
    assert "true) args+=(--use-global-config)" in action
    assert "false) args+=(--no-global-config)" in action


def test_marketplace_kicker_supports_metadata_sync():
    workflow = (
        GITHUB / "workflows/bos-universal-marketplace-kicker.yml"
    ).read_text(encoding="utf-8")

    assert "options: [validate, name-check, release, metadata]" in workflow
    assert "config_path: .github/bos-universal-config.json" in workflow
    assert "workflows/repo-metadata-sync.yml@main" in workflow
    assert "needs.release.outputs.tag_name" in workflow
    assert "REPO_ADMIN_PAT: ${{ secrets.REPO_ADMIN_PAT }}" in workflow
    assert "RELEASE_PAT: ${{ secrets.RELEASE_PAT }}" in workflow

    release_job = workflow.split("  release:", 1)[1].split("  metadata:", 1)[0]
    assert "models: read" in release_job


def test_security_kicker_routes_dev_and_main_with_required_permissions():
    workflow = (
        GITHUB / "workflows/bos-universal-security-kicker.yml"
    ).read_text(encoding="utf-8")

    assert "workflows/bos-universal-security.yml@dev" in workflow
    assert "workflows/bos-universal-security.yml@main" in workflow
    assert workflow.count("config_authoritative: true") == 2
    assert workflow.count("security-events: write") == 2
    assert workflow.count("scanning_pat: ${{ secrets.SCANNING_PAT }}") == 2


def test_action_test_kicker_routes_dev_and_main_read_only():
    workflow = (
        GITHUB / "workflows/bos-universal-action-test-kicker.yml"
    ).read_text(encoding="utf-8")

    assert "workflows/bos-universal-action-test.yml@dev" in workflow
    assert "workflows/bos-universal-action-test.yml@main" in workflow
    assert "contents: write" not in workflow
    assert "secrets:" not in workflow


def test_codeql_caller_avoids_duplicate_pull_request_scanner():
    workflow = (GITHUB / "workflows/codeql.yml").read_text(encoding="utf-8")

    assert "workflows/security-scan.yml@main" in workflow
    assert "enable_kit_composite: ${{ github.event_name != 'pull_request' }}" in workflow
    assert "codeql_languages: '[\"python\", \"actions\"]'" in workflow
