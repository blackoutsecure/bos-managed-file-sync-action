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
    assert load_repo_config(None) == {}


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
