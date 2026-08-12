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
    sync_direction,
)
from sync_kit.errors import ConfigError


def test_finds_default_config_name(repo):
    repo.write_config({"services": ["common"]})
    assert find_config(repo.root).name == "bos-universal-config.json"


def test_prefers_dotgithub_universal_config_when_both_exist(repo):
    repo.write_config({"services": ["common"]}, name="bos-universal-config.json")
    preferred = repo.write_config({"services": ["python"]}, name=".github/bos-universal-config.json")
    assert find_config(repo.root) == preferred


def test_returns_none_when_no_config_present(repo):
    assert find_config(repo.root) is None


def test_explicit_missing_config_raises(repo):
    with pytest.raises(ConfigError):
        find_config(repo.root, "nope.json")


def test_invalid_json_raises(repo):
    path = repo.write("bos-universal-config.json", "{ not json")
    with pytest.raises(ConfigError):
        load_repo_config(path)


def test_non_utf8_config_raises_config_error(repo):
    path = repo.root / "bos-universal-config.json"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(ConfigError, match="UTF-8"):
        load_repo_config(path)


def test_non_object_root_raises(repo):
    path = repo.write("managed-file-sync.json", json.dumps([1, 2, 3]))
    with pytest.raises(ConfigError):
        load_repo_config(path)


def test_section_defaults_to_root_object(repo):
    path = repo.write("managed-file-sync.json", json.dumps({"services": ["common"]}))
    assert load_repo_config(path, use_marketplace=False)["services"] == ["common"]


def test_no_config_file_yields_empty_section():
    config = load_repo_config(None, use_marketplace=False)
    assert config == {
        "direction": "source-to-destination",
        "variables": {"fallback_default_runner": "ubuntu-latest"},
    }


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


def test_sync_direction_defaults_and_accepts_one_way_mode():
    assert sync_direction({}) == "source-to-destination"
    assert sync_direction({"direction": "source-to-destination"}) == "source-to-destination"


@pytest.mark.parametrize("direction", ["destination-to-source", "bidirectional", "reverse", None])
def test_sync_direction_rejects_unsupported_modes(direction):
    with pytest.raises(ConfigError, match="source-to-destination"):
        sync_direction({"direction": direction})


@pytest.mark.parametrize("namespace", ["bad:namespace", "bad namespace", "bad\nnamespace"])
def test_marker_namespace_rejects_unsafe_characters(namespace):
    with pytest.raises(ConfigError):
        marker_namespace({"marker_namespace": namespace})


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
    assert variables["project_name"] == "demo"
    assert variables["year"].isdigit()


def test_builtin_runner_variables_default_to_fallback(monkeypatch):
    monkeypatch.delenv("DEFAULT_RUNNER", raising=False)
    monkeypatch.delenv("RUNNER_X64", raising=False)
    monkeypatch.delenv("RUNNER_ARM64", raising=False)

    variables = builtin_variables()

    assert variables["fallback_default_runner"] == "ubuntu-latest"
    assert variables["DEFAULT_RUNNER"] == "ubuntu-latest"
    assert variables["RUNNER_X64"] == "ubuntu-latest"
    assert variables["RUNNER_ARM64"] == "ubuntu-latest"


def test_builtin_runner_variables_use_valid_env_values(monkeypatch):
    monkeypatch.setenv("DEFAULT_RUNNER", "ubuntu-latest")
    monkeypatch.setenv("RUNNER_X64", "ubuntu-24.04")
    monkeypatch.setenv("RUNNER_ARM64", "[\"ubuntu-24.04-arm\"]")

    variables = builtin_variables()

    assert variables["DEFAULT_RUNNER"] == "ubuntu-latest"
    assert variables["RUNNER_X64"] == "ubuntu-24.04"
    assert variables["RUNNER_ARM64"] == "[\"ubuntu-24.04-arm\"]"


def test_builtin_runner_variables_invalid_env_values_fallback(monkeypatch):
    monkeypatch.setenv("DEFAULT_RUNNER", "")
    monkeypatch.setenv("RUNNER_X64", "ubuntu latest")
    monkeypatch.setenv("RUNNER_ARM64", "[not-json]")

    variables = builtin_variables()

    assert variables["DEFAULT_RUNNER"] == "ubuntu-latest"
    assert variables["RUNNER_X64"] == "ubuntu-latest"
    assert variables["RUNNER_ARM64"] == "ubuntu-latest"


def test_selected_runner_auto_detects_runtime_arch(monkeypatch):
    monkeypatch.setenv("DEFAULT_RUNNER", "ubuntu-latest")
    monkeypatch.setenv("RUNNER_X64", "ubuntu-24.04")
    monkeypatch.setenv("RUNNER_ARM64", "ubuntu-24.04-arm")
    monkeypatch.setenv("RUNNER_ARCH", "ARM64")
    monkeypatch.setenv("MFS_WORKLOAD_ARCH", "auto")

    variables = builtin_variables()

    assert variables["WORKLOAD_ARCH"] == "auto"
    assert variables["SELECTED_RUNNER"] == "ubuntu-24.04-arm"


def test_selected_runner_explicit_override(monkeypatch):
    monkeypatch.setenv("DEFAULT_RUNNER", "ubuntu-latest")
    monkeypatch.setenv("RUNNER_X64", "ubuntu-24.04")
    monkeypatch.setenv("RUNNER_ARM64", "ubuntu-24.04-arm")
    monkeypatch.setenv("RUNNER_ARCH", "ARM64")
    monkeypatch.setenv("MFS_WORKLOAD_ARCH", "x64")

    variables = builtin_variables()

    assert variables["WORKLOAD_ARCH"] == "x64"
    assert variables["SELECTED_RUNNER"] == "ubuntu-24.04"


def test_config_runner_overrides_drive_selected_runner(monkeypatch):
    monkeypatch.delenv("DEFAULT_RUNNER", raising=False)
    monkeypatch.delenv("RUNNER_X64", raising=False)
    monkeypatch.delenv("RUNNER_ARM64", raising=False)
    monkeypatch.setenv("RUNNER_ARCH", "ARM64")
    monkeypatch.setenv("MFS_WORKLOAD_ARCH", "auto")

    variables = builtin_variables(
        {
            "fallback_default_runner": "self-hosted",
            "DEFAULT_RUNNER": "default-pool",
            "RUNNER_X64": "x64-pool",
            "RUNNER_ARM64": "arm64-pool",
        }
    )

    assert variables["fallback_default_runner"] == "self-hosted"
    assert variables["SELECTED_RUNNER"] == "arm64-pool"


def test_invalid_config_runner_override_uses_configured_fallback(monkeypatch):
    monkeypatch.delenv("MFS_WORKLOAD_ARCH", raising=False)

    variables = builtin_variables(
        {
            "fallback_default_runner": "self-hosted",
            "DEFAULT_RUNNER": "invalid runner",
            "WORKLOAD_ARCH": "default",
        }
    )

    assert variables["DEFAULT_RUNNER"] == "self-hosted"
    assert variables["SELECTED_RUNNER"] == "self-hosted"


def test_selected_runner_auto_invalid_runtime_falls_back_default(monkeypatch):
    monkeypatch.setenv("DEFAULT_RUNNER", "ubuntu-latest")
    monkeypatch.setenv("RUNNER_X64", "ubuntu-24.04")
    monkeypatch.setenv("RUNNER_ARM64", "ubuntu-24.04-arm")
    monkeypatch.setenv("RUNNER_ARCH", "MIPS")
    monkeypatch.setenv("MFS_WORKLOAD_ARCH", "auto")

    variables = builtin_variables()

    assert variables["SELECTED_RUNNER"] == "ubuntu-latest"


def test_marketplace_config_is_loaded_by_default():
    """Marketplace config should be loaded when no files are provided."""
    config = load_repo_config(None, use_marketplace=True)
    # Marketplace should include these by default
    assert "common" in config.get("services", [])
    assert "lf_line_endings" in config.get("services", [])
    assert "dependabot_actions" in config.get("services", [])
    assert "dotfiles" in config.get("services", [])
    assert config.get("direction") == "source-to-destination"
    assert config.get("marker_namespace") == "managed-file-sync"
    assert "exclude_paths" not in config


def test_marketplace_config_can_be_disabled():
    """use_marketplace_config: false should disable marketplace tier."""
    config = load_repo_config(None, use_marketplace=False)
    # Switchable marketplace defaults are disabled, but locked defaults remain.
    assert config["direction"] == "source-to-destination"
    assert config["variables"]["fallback_default_runner"] == "ubuntu-latest"
    assert "services" not in config


def test_repo_config_can_disable_marketplace(repo):
    repo_path = repo.write(
        "bos-universal-config.json",
        json.dumps(
            {
                "managed_file_sync": {
                    "use_marketplace_config": False,
                    "services": ["custom"],
                }
            }
        ),
    )

    config = load_repo_config(repo_path, use_marketplace=True)

    assert config["services"] == ["custom"]
    assert "common" not in config.get("service_definitions", {})


def test_repo_config_can_reenable_marketplace_disabled_by_global_config(repo):
    global_path = repo.write(
        ".github/blackout-secure-managed-file-sync-global-config.json",
        json.dumps(
            {
                "managed_file_sync": {
                    "use_marketplace_config": False,
                    "services": ["dotfiles"],
                }
            }
        ),
    )
    repo_path = repo.write(
        "bos-universal-config.json",
        json.dumps(
            {
                "managed_file_sync": {
                    "use_marketplace_config": True,
                    "services": ["prettier"],
                }
            }
        ),
    )

    config = load_repo_config(repo_path, global_path, use_marketplace=True)

    assert config["services"] == [
        "common",
        "lf_line_endings",
        "markdownlint",
        "dependabot_actions",
        "dotfiles",
        "prettier",
    ]
    assert "common" in config["service_definitions"]


def test_use_marketplace_config_must_be_boolean(repo):
    repo_path = repo.write(
        "bos-universal-config.json",
        json.dumps({"managed_file_sync": {"use_marketplace_config": "false"}}),
    )

    with pytest.raises(ConfigError, match="use_marketplace_config"):
        load_repo_config(repo_path, use_marketplace=True)


def test_repo_config_merges_with_marketplace(repo):
    """Repo config appends services to marketplace by default and merges variables."""
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
    # Services append to marketplace defaults by default.
    assert config["services"] == [
        "common",
        "lf_line_endings",
        "markdownlint",
        "dependabot_actions",
        "dotfiles",
        "prettier",
    ]
    # Marketplace marker_namespace should be inherited
    assert config.get("marker_namespace") == "managed-file-sync"
    # Variables should have both marketplace (empty) and repo-specific
    assert config["variables"].get("project_name") == "test-project"


def test_global_and_repo_configs_merge(repo):
    """Global config should merge with repo config."""
    global_path = repo.write(
        ".github/blackout-secure-managed-file-sync-global-config.json",
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
    # Repo services append to global by default.
    assert config["services"] == ["common", "dotfiles", "prettier"]
    # Variables merge (org variables + repo variables)
    assert config["variables"]["org_name"] == "my-org"
    assert config["variables"]["project_name"] == "my-project"


def test_marketplace_global_and_repo_cascade(repo):
    """All three tiers should merge in cascade."""
    global_path = repo.write(
        ".github/blackout-secure-managed-file-sync-global-config.json",
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
    assert config["services"] == [
        "common",
        "lf_line_endings",
        "markdownlint",
        "dependabot_actions",
        "dotfiles",
        "prettier",
    ]
    assert config["variables"]["org_name"] == "my-org"  # Global
    assert config["variables"]["project_name"] == "my-project"  # Repo
    assert "exclude_paths" not in config


def test_use_marketplace_services_false_replaces_instead_of_appending(repo):
    repo_path = repo.write(
        "bos-universal-config.json",
        json.dumps(
            {
                "managed_file_sync": {
                    "use_marketplace_services": False,
                    "services": ["prettier"],
                }
            }
        ),
    )
    config = load_repo_config(repo_path, use_marketplace=True)
    assert config["services"] == ["prettier"]


def test_repo_cannot_override_locked_direction(repo):
    repo_path = repo.write(
        "bos-universal-config.json",
        json.dumps(
            {
                "managed_file_sync": {
                    "direction": "destination-to-source",
                    "services": ["common"],
                }
            }
        ),
    )

    with pytest.raises(ConfigError, match="locked"):
        load_repo_config(repo_path, use_marketplace=True)


def test_repo_cannot_override_locked_fallback_runner(repo):
    repo_path = repo.write(
        "bos-universal-config.json",
        json.dumps(
            {
                "managed_file_sync": {
                    "variables": {
                        "fallback_default_runner": "self-hosted",
                        "project_name": "demo",
                    }
                }
            }
        ),
    )

    with pytest.raises(ConfigError, match="variables.fallback_default_runner"):
        load_repo_config(repo_path, use_marketplace=True)


def test_exclude_services_lists_are_appended(repo):
    global_path = repo.write(
        ".github/blackout-secure-managed-file-sync-global-config.json",
        json.dumps({"managed_file_sync": {"exclude_services": ["common"]}}),
    )
    repo_path = repo.write(
        "bos-universal-config.json",
        json.dumps({"managed_file_sync": {"exclude_services": ["markdownlint"]}}),
    )
    config = load_repo_config(repo_path, global_path, use_marketplace=True)
    assert config["exclude_services"] == ["common", "markdownlint"]


def test_use_marketplace_services_must_be_boolean(repo):
    repo_path = repo.write(
        "bos-universal-config.json",
        json.dumps({"managed_file_sync": {"use_marketplace_services": "false", "services": ["common"]}}),
    )
    with pytest.raises(ConfigError):
        load_repo_config(repo_path, use_marketplace=True)


def test_exclude_services_must_be_list(repo):
    repo_path = repo.write(
        "bos-universal-config.json",
        json.dumps({"managed_file_sync": {"exclude_services": "common"}}),
    )
    with pytest.raises(ConfigError):
        load_repo_config(repo_path, use_marketplace=True)
