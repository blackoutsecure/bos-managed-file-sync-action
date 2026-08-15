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


def test_public_bundle_contains_only_action_owned_config():
    bundle = _json(ROOT / "src/sync_kit/managed-file-sync-marketplace-config.json")

    assert set(bundle) == {"managed_file_sync"}
    assert (GITHUB / "bos-universal-config.json").is_file()
    workflows = sorted((GITHUB / "workflows").glob("bos-universal-*-kicker.yml"))
    assert len(workflows) == 4
    for workflow in workflows:
        document = workflow.read_text(encoding="utf-8")
        assert "Customize via `.github/bos-universal-config.json`, not this file." in document
        assert "Customize via `bos-universal-config.json`, not this file." not in document

    marketplace_workflow = (
        GITHUB / "workflows/bos-universal-marketplace-kicker.yml"
    ).read_text(encoding="utf-8")
    assert "config_path: .github/bos-universal-config.json" in marketplace_workflow

    section = load_repo_config(config_file=None, global_config_file=None)
    registry = load_catalog(ROOT, section, section_is_merged=True)
    resolved = resolve_services(registry, section)

    assert [service.name for service in resolved] == [
        "common",
        "lf_line_endings",
        "markdownlint",
        "dependabot_actions",
        "dependabot_pip",
        "editorconfig",
    ]


def test_kickers_use_hub_shared_ref_resolver():
    workflows = sorted((GITHUB / "workflows").glob("bos-universal-*-kicker.yml"))

    for workflow in workflows:
        document = workflow.read_text(encoding="utf-8")
        assert (
            "uses: blackoutsecure/bos-automation-hub/.github/actions/shared/resolve-hub-ref@main"
            in document
        )
        assert "case \"${EVENT_NAME}\" in" not in document

    security = (GITHUB / "workflows/bos-universal-security-kicker.yml").read_text(
        encoding="utf-8"
    )
    assert "merge_group_base_ref: ${{ github.event.merge_group.base_ref }}" in security


def test_external_hub_policy_can_supply_companion_sections():
    config = load_repo_config(
        global_config_json=json.dumps(
            {
                "organization": {"reporting": {"title_prefix": "Example Org"}},
                "security": {"enable_code_scan": True},
                "marketplace": {"target_branch": "main"},
                "general": {"action_test": {"python_versions": ["3.12"]}},
            }
        )
    )

    assert config["organization"]["reporting"]["title_prefix"] == "Example Org"
    assert config["security"] == {"enable_code_scan": True}
    assert config["marketplace"] == {"target_branch": "main"}
    assert config["general"]["action_test"] == {"python_versions": ["3.12"]}


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


def test_composite_preflight_diagnostics_do_not_bypass_reporting_policy():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")

    assert 'echo "use_global_config must be' in action
    assert 'echo "::error::use_global_config must be' not in action


def test_codeql_caller_avoids_duplicate_pull_request_scanner():
    workflow = (GITHUB / "workflows/codeql.yml").read_text(encoding="utf-8")

    assert "workflows/security-scan.yml@main" in workflow
    assert "enable_kit_composite: ${{ github.event_name != 'pull_request' }}" in workflow
    assert "codeql_languages: '[\"python\", \"actions\"]'" in workflow


def test_package_constants_match_pyproject():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    name = re.search(r'^name = "([^"]+)"', pyproject, re.MULTILINE)
    author = re.search(
        r'^authors = \[\{name = "([^"]+)", email = "([^"]+)"\}\]',
        pyproject,
        re.MULTILINE,
    )
    description = re.search(r'^description = "([^"]+)"', pyproject, re.MULTILINE)

    assert name is not None and author is not None and description is not None
    assert name.group(1) == metadata.PACKAGE_NAME
    assert author.group(1) == metadata.PACKAGE_AUTHOR
    assert author.group(2) == metadata.PACKAGE_SUPPORT_EMAIL
    assert description.group(1) == metadata.PACKAGE_DESCRIPTION
    assert _toml_value(pyproject, "project", "license") == metadata.PACKAGE_LICENSE
    assert _toml_value(pyproject, "project", "license-files") == ["LICENSE", "NOTICE"]
    assert _toml_value(pyproject, "project.urls", "Homepage") == metadata.PACKAGE_WEBSITE
    assert _toml_value(pyproject, "project.urls", "Repository") == metadata.PACKAGE_REPOSITORY
    assert (
        _toml_value(pyproject, "project.urls", "Documentation")
        == metadata.PACKAGE_DOCUMENTATION
    )
    assert _toml_value(pyproject, "project.urls", "Issues") == metadata.PACKAGE_ISSUES
    assert _toml_value(pyproject, "project.urls", "Changelog") == metadata.PACKAGE_RELEASES
    assert _toml_value(pyproject, "project.urls", "Marketplace") == metadata.PACKAGE_MARKETPLACE


def test_package_legal_identity_matches_readme_and_notice():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")

    assert metadata.PACKAGE_COPYRIGHT in readme
    assert metadata.PACKAGE_COPYRIGHT.replace(" ©", "") in notice
    assert metadata.PACKAGE_WEBSITE in readme


def test_marketplace_config_declares_no_package_metadata():
    section = load_repo_config(use_marketplace=True)
    assert not set(section) & set(metadata.RESERVED_METADATA_KEYS)


def test_package_title_matches_action_name():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    assert _yaml_scalar(action, "name") == metadata.PACKAGE_TITLE
