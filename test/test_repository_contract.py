"""Repository-level contracts shared with bos-automation-hub."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from sync_kit import __version__, metadata
from sync_kit.catalog import load_catalog, resolve_services
from sync_kit.config import load_repo_config

ROOT = Path(__file__).resolve().parents[1]
GITHUB = ROOT / ".github"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _toml_value(document: str, section: str, key: str):
    section_match = re.search(
        rf"^\[{re.escape(section)}\]\s*$\n(?P<body>.*?)(?=^\[|\Z)",
        document,
        re.MULTILINE | re.DOTALL,
    )
    assert section_match, f"missing TOML section {section!r}"
    value_match = re.search(
        rf"^{re.escape(key)}\s*=\s*(?P<value>\[[\s\S]*?\]|\"[^\"]*\")\s*$",
        section_match.group("body"),
        re.MULTILINE,
    )
    assert value_match, f"missing TOML value {section}.{key}"
    return ast.literal_eval(value_match.group("value"))


def _yaml_scalar(document: str, key: str, *, indent: int = 0) -> str:
    prefix = " " * indent
    matches = re.findall(
        rf"^{re.escape(prefix + key)}:\s*(?:'([^']*)'|\"([^\"]*)\"|([^\s#]+))\s*$",
        document,
        re.MULTILINE,
    )
    assert len(matches) == 1, f"expected exactly one {key!r} scalar at indent {indent}"
    return next(value for value in matches[0] if value)


def _folded_json(document: str, key: str, *, indent: int) -> dict:
    prefix = " " * indent
    match = re.search(
        rf"^{re.escape(prefix + key)}: >-\n^{re.escape(prefix + '  ')}(.+)$",
        document,
        re.MULTILINE,
    )
    assert match is not None, f"expected folded JSON value for {key!r}"
    return json.loads(match.group(1))


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


def test_managed_file_config_uses_marketplace_defaults():
    repo_path = GITHUB / "bos-universal-config.json"
    section = load_repo_config(config_file=repo_path)
    registry = load_catalog(ROOT, section, section_is_merged=True)
    section["services"] = [name for name in section["services"] if name in registry]
    resolved = resolve_services(registry, section)

    assert section["use_marketplace_config"] is True
    assert [service.name for service in resolved] == [
        "common",
        "lf_line_endings",
        "markdownlint",
        "dependabot_actions",
        "dependabot_pip",
        "editorconfig",
    ]


def test_marketplace_profiles_are_opt_in():
    config = load_repo_config(config_file=GITHUB / "bos-universal-config.json")
    assert "quality_baseline" not in config["services"]


def test_repo_selects_required_opt_in_hub_kickers():
    config = _json(GITHUB / "bos-universal-config.json")
    assert config["managed_file_sync"]["services"] == [
        "bos_universal_action_test_kicker",
        "bos_universal_marketplace_kicker",
    ]


def test_repository_has_only_canonical_universal_config():
    assert (GITHUB / "bos-universal-config.json").is_file()
    assert not (ROOT / "bos-universal-config.json").exists()


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


def test_marketplace_recommendations_match_project_toolchain():
    config = load_repo_config(None)
    toolchain = config["recommended_toolchain"]
    python = toolchain["python"]
    dependencies = toolchain["dependencies"]
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    action = (ROOT / "action.yml").read_text(encoding="utf-8")

    assert toolchain["advisory"] is True
    assert python["requires"] == _toml_value(pyproject, "project", "requires-python")
    assert dependencies["build"] == _toml_value(pyproject, "build-system", "requires")
    assert dependencies["runtime"] == _toml_value(pyproject, "project", "dependencies")
    assert dependencies["development"] == _toml_value(
        pyproject,
        "project.optional-dependencies",
        "dev",
    )
    assert config["security"]["python_version"] == python["default_version"]
    assert config["security"]["python_packages"] == dependencies["development"]
    assert config["general"]["action_test"]["python_versions"] == python["tested_versions"]
    assert config["general"]["action_test"]["python_packages"] == dependencies["development"]

    python_input = re.search(
        r"^  python_version:\s*$\n(?P<body>(?:    .*\n)+)",
        action,
        re.MULTILINE,
    )
    assert python_input
    assert _yaml_scalar(python_input.group("body"), "default", indent=4) == python["default_version"]


def test_composite_action_runs_isolated_bundled_source_without_installing():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")

    assert 'python3 -I "${GITHUB_ACTION_PATH}/src/sync_kit/_bootstrap.py" apply' in action
    assert "GITHUB_TOKEN:            ${{ github.token }}" in action
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
    assert "workflows/repo-metadata-sync.yml@main" in workflow
    assert "needs.release.outputs.tag_name" in workflow
    assert "secrets: inherit" in workflow

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
    assert workflow.count("secrets: inherit") == 2


def test_action_test_kicker_uses_stable_hub_workflow_read_only():
    workflow = (
        GITHUB / "workflows/bos-universal-action-test-kicker.yml"
    ).read_text(encoding="utf-8")

    assert workflow.count("workflows/bos-universal-action-test.yml@main") == 2
    assert "workflows/bos-universal-action-test.yml@dev" not in workflow
    assert "contents: write" not in workflow
    assert "secrets:" not in workflow


def test_sync_kicker_routes_to_branch_specific_hub_workflows():
    workflow = (
        GITHUB / "workflows/bos-universal-sync-kicker.yml"
    ).read_text(encoding="utf-8")

    assert "- cron: '29 14 * * 1'" in workflow
    assert "- '.github/bos-universal-config.json'" in workflow
    assert "name: Resolve target hub ref" in workflow
    assert "workflows/bos-universal-sync.yml@dev" in workflow
    assert "workflows/bos-universal-sync.yml@main" in workflow
    assert workflow.count("secrets: inherit") == 2
    assert "global_config_json: >-" not in workflow
    assert "actions/shared/commit-and-push@main" not in workflow


def test_codeql_caller_avoids_duplicate_pull_request_scanner():
    workflow = (GITHUB / "workflows/codeql.yml").read_text(encoding="utf-8")

    assert "workflows/security-scan.yml@main" in workflow
    assert "enable_kit_composite: ${{ github.event_name != 'pull_request' }}" in workflow
    assert "codeql_languages: '[\"python\", \"actions\"]'" in workflow


def test_package_constants_match_pyproject():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    name = re.search(r'^name = "([^"]+)"', pyproject, re.MULTILINE)
    author = re.search(r'^authors = \[\{name = "([^"]+)"\}\]', pyproject, re.MULTILINE)
    description = re.search(r'^description = "([^"]+)"', pyproject, re.MULTILINE)

    assert name is not None and author is not None and description is not None
    assert name.group(1) == metadata.PACKAGE_NAME
    assert author.group(1) == metadata.PACKAGE_AUTHOR
    assert description.group(1) == metadata.PACKAGE_DESCRIPTION


def test_marketplace_config_declares_no_package_metadata():
    section = load_repo_config(use_marketplace=True)
    assert not set(section) & set(metadata.RESERVED_METADATA_KEYS)


def test_package_title_matches_action_name():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    assert _yaml_scalar(action, "name") == metadata.PACKAGE_TITLE
