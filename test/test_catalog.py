"""Service catalog parsing, layering, and resolution."""

from __future__ import annotations

import pytest

from sync_kit.catalog import check_conflicts, load_catalog, parse_service, resolve_services
from sync_kit.errors import ConfigError

DEFAULT_SERVICES = (
    "common",
    "lf_line_endings",
    "dependabot_actions",
    "dotfiles",
    "codeowners",
    "license",
    "notice_apache2",
    "shellcheck",
    "prettier",
    "markdownlint",
)


@pytest.mark.parametrize("name", DEFAULT_SERVICES)
def test_default_catalog_contains_expected_service(repo, name):
    assert name in load_catalog(repo.root)


def test_repo_definitions_override_catalog(repo):
    section = {
        "service_definitions": {
            "common": {"mode": "file", "files": [{"path": "OVERRIDE.txt", "content": "mine"}]},
        }
    }
    assert load_catalog(repo.root, section)["common"].files[0].path == "OVERRIDE.txt"


def test_extra_catalog_layers_on_top_of_defaults(repo):
    catalog_file = repo.write(
        "org-catalog.json",
        '{"services": {"org_policy": {"mode": "init", "files": [{"path": "POLICY.md", "content": "x"}]}}}',
    )
    catalog = load_catalog(repo.root, catalog_paths=[catalog_file])
    assert "org_policy" in catalog
    assert "common" in catalog


def test_default_catalog_can_be_disabled(repo):
    section = {"service_definitions": {"custom": {"files": [{"path": "a.txt", "content": "x"}]}}}
    assert list(load_catalog(repo.root, section, include_defaults=False)) == ["custom"]


def test_rejects_path_traversal():
    with pytest.raises(ConfigError):
        parse_service("evil", {"mode": "file", "files": [{"path": "../outside.txt", "content": "x"}]})


def test_rejects_absolute_path():
    with pytest.raises(ConfigError):
        parse_service("evil", {"mode": "file", "files": [{"path": "/etc/passwd", "content": "x"}]})


def test_rejects_content_file_traversal(repo):
    with pytest.raises(ConfigError):
        parse_service(
            "evil",
            {"mode": "file", "files": [{"path": "a.txt", "content_file": "../../etc/passwd"}]},
            [repo.root],
        )


def test_rejects_unknown_mode():
    with pytest.raises(ConfigError):
        parse_service("bad", {"mode": "teleport", "files": [{"path": "a.txt", "content": "x"}]})


def test_requires_files():
    with pytest.raises(ConfigError):
        parse_service("bad", {"mode": "file", "files": []})


def test_requires_content_source():
    with pytest.raises(ConfigError):
        parse_service("bad", {"mode": "file", "files": [{"path": "a.txt"}]})


def test_content_file_is_loaded(repo):
    repo.write("templates/body.txt", "hello\n")
    service = parse_service(
        "tpl",
        {"mode": "file", "files": [{"path": "out.txt", "content_file": "templates/body.txt"}]},
        [repo.root],
    )
    assert service.files[0].content == "hello\n"


def test_per_file_mode_overrides_service_mode():
    service = parse_service(
        "mixed",
        {
            "mode": "block",
            "files": [
                {"path": "a.txt", "content": "x"},
                {"path": "b.txt", "content": "y", "mode": "init"},
            ],
        },
    )
    assert [f.mode for f in service.files] == ["block", "init"]


def test_resolve_services_from_list(repo):
    catalog = load_catalog(repo.root)
    services = resolve_services(catalog, {"services": ["common", "dotfiles"]})
    assert [s.name for s in services] == ["common", "dotfiles"]


def test_resolve_services_from_mapping(repo):
    catalog = load_catalog(repo.root)
    services = resolve_services(catalog, {"services": {"common": True, "prettier": False}})
    assert [s.name for s in services] == ["common"]


def test_disabled_services_are_skipped(repo):
    catalog = load_catalog(repo.root)
    section = {"services": ["common", "dotfiles"], "disabled_services": ["dotfiles"]}
    assert [s.name for s in resolve_services(catalog, section)] == ["common"]


def test_wildcard_selects_every_file_service(repo):
    catalog = load_catalog(repo.root)
    concrete = [name for name, service in catalog.items() if not service.includes]
    assert len(resolve_services(catalog, {"services": ["*"]})) == len(concrete)


def test_unknown_service_raises(repo):
    with pytest.raises(ConfigError):
        resolve_services(load_catalog(repo.root), {"services": ["does_not_exist"]})


def test_input_services_override_config(repo):
    catalog = load_catalog(repo.root)
    services = resolve_services(catalog, {"services": ["common"]}, ["dotfiles"])
    assert [s.name for s in services] == ["dotfiles"]


def test_bundle_expands_to_members(repo):
    catalog = load_catalog(repo.root)
    services = resolve_services(catalog, {"services": ["baseline"]})
    assert [s.name for s in services] == ["common", "lf_line_endings", "dotfiles", "markdownlint"]


def test_bundle_members_are_deduplicated(repo):
    catalog = load_catalog(repo.root)
    services = resolve_services(catalog, {"services": ["common", "baseline"]})
    assert [s.name for s in services].count("common") == 1


def test_disabled_service_is_dropped_from_bundle(repo):
    catalog = load_catalog(repo.root)
    section = {"services": ["baseline"], "disabled_services": ["markdownlint"]}
    assert "markdownlint" not in [s.name for s in resolve_services(catalog, section)]


def test_bundle_cycle_is_rejected(repo):
    section = {
        "service_definitions": {
            "a": {"includes": ["b"]},
            "b": {"includes": ["a"]},
        }
    }
    catalog = load_catalog(repo.root, section)
    with pytest.raises(ConfigError):
        resolve_services(catalog, {"services": ["a"]})


def test_bundle_cannot_also_define_files():
    with pytest.raises(ConfigError):
        parse_service(
            "bad",
            {"includes": ["common"], "files": [{"path": "a.txt", "content": "x"}]},
        )


def test_absent_mode_needs_no_content():
    service = parse_service("retired", {"mode": "absent", "files": [{"path": "OLD.md"}]})
    assert service.files[0].mode == "absent"


def test_scaffold_is_parsed_from_lines():
    service = parse_service(
        "dep",
        {
            "files": [
                {
                    "path": ".github/dependabot.yml",
                    "scaffold": ["version: 2", "updates:"],
                    "content": "  - package-ecosystem: npm",
                }
            ]
        },
    )
    assert service.files[0].scaffold == "version: 2\nupdates:"


def test_scaffold_is_rejected_outside_block_mode():
    with pytest.raises(ConfigError):
        parse_service(
            "bad",
            {"mode": "file", "files": [{"path": "a.yml", "content": "x", "scaffold": "y"}]},
        )


def test_conflicting_whole_file_services_are_rejected(repo):
    section = {
        "services": ["lint_python", "lint_node"],
        "service_definitions": {
            "lint_python": {"mode": "file", "files": [{"path": "lint.yml", "content": "py"}]},
            "lint_node": {"mode": "file", "files": [{"path": "lint.yml", "content": "node"}]},
        },
    }
    catalog = load_catalog(repo.root, section)
    with pytest.raises(ConfigError):
        resolve_services(catalog, section)


def test_block_services_may_share_a_path(repo):
    section = {
        "services": ["a", "b"],
        "service_definitions": {
            "a": {"files": [{"path": ".gitignore", "content": "a/"}]},
            "b": {"files": [{"path": ".gitignore", "content": "b/"}]},
        },
    }
    catalog = load_catalog(repo.root, section)
    assert len(resolve_services(catalog, section)) == 2


def test_check_conflicts_accepts_a_single_owner(repo):
    catalog = load_catalog(repo.root)
    check_conflicts(resolve_services(catalog, {"services": ["markdownlint"]}))
