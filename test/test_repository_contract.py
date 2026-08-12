"""Repository-level contracts shared with bos-automation-hub."""

from __future__ import annotations

import json
from pathlib import Path

from sync_kit.catalog import load_catalog, resolve_services
from sync_kit.config import load_repo_config

ROOT = Path(__file__).resolve().parents[1]
GITHUB = ROOT / ".github"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_managed_file_config_cascade_uses_known_services():
    repo_path = GITHUB / "bos-universal-config.json"
    section = load_repo_config(config_file=repo_path)
    registry = load_catalog(ROOT, section, section_is_merged=True)
    resolved = resolve_services(registry, section)

    assert [service.name for service in resolved] == [
        "common",
        "lf_line_endings",
        "markdownlint",
    ]


def test_universal_marketplace_publication_contract():
    config = _json(GITHUB / "bos-universal-config.json")
    marketplace = config["marketplace"]

    assert "source_branch" not in marketplace
    assert marketplace["target_branch"] == "main"
    assert marketplace["include_dependabot_config"] is True
    assert marketplace["include_github_metadata"] is False
    assert {
        ".github/dependabot.yml",
        "action.yml",
        "src",
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "NOTICE",
    } <= set(marketplace["required_paths"])
    assert ".gitignore" not in marketplace["allowlist_paths"]
    assert "test/**" not in marketplace["allowlist_paths"]
    assert config["general"] == {
        "action_test": {"python_versions": ["3.10", "3.11", "3.12"]}
    }
    assert "managed_file_sync" not in config


def test_sync_kicker_calls_published_action_directly():
    workflow = (
        GITHUB / "workflows/bos-universal-sync-kicker.yml"
    ).read_text(encoding="utf-8")

    assert "uses: blackoutsecure/bos-managed-file-sync-action@v1" in workflow
    assert "use_global_config:" not in workflow
    assert "global_config_path:" not in workflow
    assert "blackout-secure-managed-file-sync-global-config.json" not in workflow
    assert "actions/shared/commit-and-push@main" in workflow
    assert "bos-universal-sync.yml@" not in workflow
    assert "resolve-target:" not in workflow


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
