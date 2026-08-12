"""Config discovery, parsing, and templating."""

from __future__ import annotations

import json

import pytest

from sync_kit.config import (
    builtin_variables,
    find_config,
    load_repo_config,
    marker_namespace,
    parse_service_list,
    render,
    string_map,
)
from sync_kit.errors import ConfigError


def test_finds_default_config_name(repo):
    repo.write_config({"services": ["common"]})
    assert find_config(repo.root).name == "bos-universal-config.json"


def test_returns_none_when_no_config_present(repo):
    assert find_config(repo.root) is None


def test_explicit_missing_config_raises(repo):
    with pytest.raises(ConfigError):
        find_config(repo.root, "nope.json")


def test_invalid_json_raises(repo):
    path = repo.write("bos-universal-config.json", "{ not json")
    with pytest.raises(ConfigError):
        load_repo_config(path)


def test_non_object_root_raises(repo):
    path = repo.write("managed-file-sync.json", json.dumps([1, 2, 3]))
    with pytest.raises(ConfigError):
        load_repo_config(path)


def test_section_defaults_to_root_object(repo):
    path = repo.write("managed-file-sync.json", json.dumps({"services": ["common"]}))
    assert load_repo_config(path)["services"] == ["common"]


def test_no_config_file_yields_empty_section():
    # Test without marketplace config (backwards compat); marketplace is enabled by default
    assert load_repo_config(None, use_marketplace=False) == {}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("common, prettier  dotfiles", ["common", "prettier", "dotfiles"]),
        ("", []),
        (None, []),
    ],
)
def test_service_list_parsing(raw, expected):
    assert parse_service_list(raw) == expected


def test_marker_namespace_defaults_and_overrides():
    assert marker_namespace({}) == "managed-file-sync"
    assert marker_namespace({"marker_namespace": "bos-automation-hub"}) == "bos-automation-hub"


def test_marker_namespace_rejects_colon():
    with pytest.raises(ConfigError):
        marker_namespace({"marker_namespace": "bad:namespace"})


def test_string_map_rejects_non_object():
    with pytest.raises(ConfigError):
        string_map(["not", "an", "object"])


def test_render_substitutes_known_tokens_only():
    assert render("{{a}}/{{b}}", {"a": "x"}) == "x/{{b}}"


def test_builtin_variables_from_github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example-org/demo")
    variables = builtin_variables()
    assert variables["owner"] == "example-org"
    assert variables["repo"] == "demo"
    assert variables["year"].isdigit()


def test_marketplace_config_is_loaded_by_default():
    """Marketplace config should be loaded when no files are provided."""
    config = load_repo_config(None, use_marketplace=True)
    # Marketplace should include these by default
    assert "common" in config.get("services", [])
    assert "lf_line_endings" in config.get("services", [])
    assert config.get("marker_namespace") == "managed-file-sync"
    assert "dependabot.yml" in config.get("exclude_paths", [])


def test_marketplace_config_can_be_disabled():
    """use_marketplace_config: false should disable marketplace tier."""
    config = load_repo_config(None, use_marketplace=False)
    # Without marketplace, empty config
    assert config == {}


def test_repo_config_merges_with_marketplace(repo):
    """Repo config should merge (not replace) marketplace config for variables, but replace services."""
    repo_path = repo.write(
        "bos-universal-config.json",
        json.dumps({
            "managed_file_sync": {
                "services": ["common", "prettier"],
                "variables": {"project_name": "test-project"},
            }
        }),
    )
    config = load_repo_config(repo_path, use_marketplace=True)
    # Services should be replaced (not merged)
    assert config["services"] == ["common", "prettier"]
    # Marketplace marker_namespace should be inherited
    assert config.get("marker_namespace") == "managed-file-sync"
    # Variables should have both marketplace (empty) and repo-specific
    assert config["variables"].get("project_name") == "test-project"


def test_global_and_repo_configs_merge(repo):
    """Global config should merge with repo config."""
    global_path = repo.write(
        ".github/bos-managed-sync-global.json",
        json.dumps({
            "managed_file_sync": {
                "services": ["common", "dotfiles"],
                "variables": {
                    "org_name": "my-org",
                    "support_email": "platform@my-org.com",
                },
            }
        }),
    )
    repo_path = repo.write(
        "bos-universal-config.json",
        json.dumps({
            "managed_file_sync": {
                "services": ["common", "prettier"],
                "variables": {"project_name": "my-project"},
            }
        }),
    )
    config = load_repo_config(repo_path, global_path, use_marketplace=False)
    # Repo services override global
    assert config["services"] == ["common", "prettier"]
    # Variables merge (org variables + repo variables)
    assert config["variables"]["org_name"] == "my-org"
    assert config["variables"]["project_name"] == "my-project"


def test_marketplace_global_and_repo_cascade(repo):
    """All three tiers should merge in cascade."""
    global_path = repo.write(
        ".github/bos-managed-sync-global.json",
        json.dumps({
            "managed_file_sync": {
                "services": ["common", "dotfiles"],
                "variables": {"org_name": "my-org"},
            }
        }),
    )
    repo_path = repo.write(
        "bos-universal-config.json",
        json.dumps({
            "managed_file_sync": {
                "services": ["common", "prettier"],
                "variables": {"project_name": "my-project"},
            }
        }),
    )
    config = load_repo_config(repo_path, global_path, use_marketplace=True)
    # Marketplace + global + repo cascade
    assert "prettier" in config["services"]  # Repo override
    assert config["variables"]["org_name"] == "my-org"  # Global
    assert config["variables"]["project_name"] == "my-project"  # Repo
    assert "dependabot.yml" in config.get("exclude_paths", [])  # Marketplace
