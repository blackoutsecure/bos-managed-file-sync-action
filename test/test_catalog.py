"""Service registry parsing, layering, and resolution."""

from __future__ import annotations

import pytest

import sync_kit.catalog as catalog_module
import sync_kit.paths as paths_module
from sync_kit.catalog import check_conflicts, load_catalog, parse_service, resolve_services
from sync_kit.errors import ConfigError

DEFAULT_SERVICES = (
    "common",
    "lf_line_endings",
    "dependabot_actions",
    "editorconfig",
    "shellcheck",
    "prettier",
    "markdownlint",
)


@pytest.mark.parametrize("name", DEFAULT_SERVICES)
def test_default_catalog_contains_expected_service(repo, name):
    assert name in load_catalog(repo.root)


def test_quality_baseline_bundle_adds_optional_quality_services(repo):
    catalog = load_catalog(repo.root)
    assert [service.name for service in resolve_services(catalog, {"services": ["quality_baseline"]})] == [
        "common",
        "lf_line_endings",
        "editorconfig",
        "markdownlint",
        "dependabot_actions",
        "shellcheck",
        "prettier",
    ]


def test_repo_definitions_override_catalog(repo):
    section = {
        "service_definitions": {
            "common": {"mode": "file", "files": [{"path": "OVERRIDE.txt", "content": "mine"}]},
        }
    }
    assert load_catalog(repo.root, section)["common"].files[0].path == "OVERRIDE.txt"


def test_custom_service_layers_on_top_of_marketplace_defaults(repo):
    section = {
        "service_definitions": {
            "org_policy": {"mode": "init", "files": [{"path": "POLICY.md", "content": "x"}]}
        }
    }
    catalog = load_catalog(repo.root, section)
    assert "org_policy" in catalog
    assert "common" in catalog


def test_rejects_path_traversal():
    with pytest.raises(ConfigError):
        parse_service("evil", {"mode": "file", "files": [{"path": "../outside.txt", "content": "x"}]})


def test_rejects_absolute_path():
    with pytest.raises(ConfigError):
        parse_service("evil", {"mode": "file", "files": [{"path": "/etc/passwd", "content": "x"}]})


def test_rejects_path_with_output_control_characters():
    with pytest.raises(ConfigError, match="non-empty relative path"):
        parse_service(
            "evil",
            {"mode": "file", "files": [{"path": "safe.txt\nforged=true", "content": "x"}]},
        )


def test_rejects_content_file_traversal(repo):
    with pytest.raises(ConfigError):
        parse_service(
            "evil",
            {"mode": "file", "files": [{"path": "a.txt", "content_file": "../../etc/passwd"}]},
            [repo.root],
        )


def test_rejects_content_file_symlink_escape(repo):
    outside = repo.root.parent / "outside-template.txt"
    outside.write_text("external\n", encoding="utf-8")
    link = repo.root / "templates" / "external.txt"
    link.parent.mkdir()
    link.symlink_to(outside)

    with pytest.raises(ConfigError, match="resolves outside"):
        parse_service(
            "evil",
            {"mode": "file", "files": [{"path": "a.txt", "content_file": "external.txt"}]},
            [repo.root / "templates"],
        )


def test_rejects_content_file_swapped_to_symlink_during_read(repo, monkeypatch):
    template = repo.write("templates/body.txt", "inside\n")
    outside = repo.root.parent / "outside-raced-template.txt"
    outside.write_text("outside\n", encoding="utf-8")
    original_resolve = paths_module.resolve_inside

    def swap_after_resolve(root, relative_path, *, key):
        candidate = original_resolve(root, relative_path, key=key)
        template.unlink()
        template.symlink_to(outside)
        return candidate

    monkeypatch.setattr(paths_module, "resolve_inside", swap_after_resolve)

    with pytest.raises(ConfigError, match="failed to read content_file"):
        parse_service(
            "safe",
            {"mode": "file", "files": [{"path": "a.txt", "content_file": "body.txt"}]},
            [repo.root / "templates"],
        )


def test_rejects_managed_files_base_swapped_to_external_symlink(repo, monkeypatch):
    managed = repo.root / "managed"
    managed.mkdir()
    (managed / "body.txt").write_text("inside\n", encoding="utf-8")
    outside = repo.root.parent / "outside-raced-managed-files"
    outside.mkdir()
    (outside / "body.txt").write_text("outside\n", encoding="utf-8")
    original_resolve = catalog_module.resolve_inside

    def swap_base_after_resolve(root, relative_path, *, key):
        candidate = original_resolve(root, relative_path, key=key)
        if key == "managed_files_path":
            managed.rename(repo.root / "original-managed")
            managed.symlink_to(outside, target_is_directory=True)
        return candidate

    monkeypatch.setattr(catalog_module, "resolve_inside", swap_base_after_resolve)

    with pytest.raises(ConfigError, match="resolves outside|failed to read"):
        load_catalog(
            repo.root,
            {
                "managed_files_path": "managed",
                "service_definitions": {
                    "safe": {
                        "mode": "file",
                        "files": [
                            {"path": "out.txt", "content_file": "body.txt"}
                        ],
                    }
                },
            },
        )


def test_rejects_unknown_mode():
    with pytest.raises(ConfigError):
        parse_service("bad", {"mode": "teleport", "files": [{"path": "a.txt", "content": "x"}]})


def test_update_mode_is_parsed():
    service = parse_service(
        "workflow",
        {"mode": "update", "files": [{"path": "workflow.yml", "content": "x"}]},
    )
    assert service.files[0].mode == "update"


@pytest.mark.parametrize("name", ["bad name", "bad\n::warning::forged", "bad:name"])
def test_rejects_unsafe_service_name(name):
    with pytest.raises(ConfigError, match="service name"):
        parse_service(name, {"mode": "file", "files": [{"path": "a.txt", "content": "x"}]})


def test_requires_files():
    with pytest.raises(ConfigError):
        parse_service("bad", {"mode": "file", "files": []})


def test_requires_content_source():
    with pytest.raises(ConfigError):
        parse_service("bad", {"mode": "file", "files": [{"path": "a.txt"}]})


def test_rejects_multiple_content_sources():
    with pytest.raises(ConfigError, match="exactly one"):
        parse_service(
            "bad",
            {
                "mode": "file",
                "files": [{"path": "a.txt", "content": "x", "content_lines": ["y"]}],
            },
        )


def test_content_lines_must_be_a_list():
    with pytest.raises(ConfigError, match="content_lines"):
        parse_service(
            "bad",
            {"mode": "file", "files": [{"path": "a.txt", "content_lines": "abc"}]},
        )


def test_rejects_comment_prefix_with_control_characters():
    with pytest.raises(ConfigError, match="comment_prefix"):
        parse_service(
            "bad",
            {
                "files": [
                    {"path": "a.txt", "content": "x", "comment_prefix": "#\n::warning::"}
                ]
            },
        )


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
    services = resolve_services(catalog, {"services": ["common", "editorconfig"]})
    assert [s.name for s in services] == ["common", "editorconfig"]


def test_prettier_uses_block_for_ignore_and_init_for_json_config(repo):
    prettier = load_catalog(repo.root)["prettier"]

    assert prettier.mode == "block"
    assert [(managed.path, managed.mode) for managed in prettier.files] == [
        (".prettierignore", "block"),
        (".prettierrc.json", "init"),
    ]


def test_resolve_services_from_mapping(repo):
    catalog = load_catalog(repo.root)
    services = resolve_services(catalog, {"services": {"common": True, "prettier": False}})
    assert [s.name for s in services] == ["common"]


def test_service_mapping_values_must_be_boolean(repo):
    with pytest.raises(ConfigError, match="true or false"):
        resolve_services(load_catalog(repo.root), {"services": {"common": "false"}})


def test_disabled_services_are_skipped(repo):
    catalog = load_catalog(repo.root)
    section = {"services": ["common", "editorconfig"], "disabled_services": ["editorconfig"]}
    assert [s.name for s in resolve_services(catalog, section)] == ["common"]


def test_exclude_services_are_skipped(repo):
    catalog = load_catalog(repo.root)
    section = {"services": ["common", "editorconfig"], "exclude_services": ["common"]}
    assert [s.name for s in resolve_services(catalog, section)] == ["editorconfig"]


def test_wildcard_selects_every_file_service(repo):
    catalog = load_catalog(repo.root)
    concrete = [name for name, service in catalog.items() if not service.includes]
    assert len(resolve_services(catalog, {"services": ["*"]})) == len(concrete)


def test_unknown_service_raises(repo):
    with pytest.raises(ConfigError):
        resolve_services(load_catalog(repo.root), {"services": ["does_not_exist"]})


def test_removed_dotfiles_service_name_is_unknown(repo):
    with pytest.raises(ConfigError, match="unknown service"):
        resolve_services(load_catalog(repo.root), {"services": ["dotfiles"]})


def test_input_services_override_config(repo):
    catalog = load_catalog(repo.root)
    services = resolve_services(catalog, {"services": ["common"]}, ["editorconfig"])
    assert [s.name for s in services] == ["editorconfig"]


def test_bundle_expands_to_members(repo):
    catalog = load_catalog(repo.root)
    services = resolve_services(catalog, {"services": ["baseline"]})
    assert [s.name for s in services] == [
        "common",
        "lf_line_endings",
        "editorconfig",
        "markdownlint",
        "dependabot_actions",
    ]


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


@pytest.mark.parametrize(("first_mode", "second_mode"), [("file", "absent"), ("block", "file")])
def test_cross_mode_path_conflicts_are_rejected(repo, first_mode, second_mode):
    section = {
        "services": ["a", "b"],
        "service_definitions": {
            "a": {"mode": first_mode, "files": [{"path": "same.txt", "content": "a"}]},
            "b": {"mode": second_mode, "files": [{"path": "same.txt", "content": "b"}]},
        },
    }
    catalog = load_catalog(repo.root, section)

    with pytest.raises(ConfigError, match="both claim"):
        resolve_services(catalog, section)


def test_normalized_path_aliases_conflict(repo):
    section = {
        "services": ["a", "b"],
        "service_definitions": {
            "a": {"mode": "file", "files": [{"path": "same.txt", "content": "a"}]},
            "b": {"mode": "file", "files": [{"path": "./same.txt", "content": "b"}]},
        },
    }

    with pytest.raises(ConfigError, match="both claim"):
        resolve_services(load_catalog(repo.root, section), section)


def test_service_cannot_claim_the_same_path_twice(repo):
    section = {
        "services": ["duplicate"],
        "service_definitions": {
            "duplicate": {
                "files": [
                    {"path": "same.txt", "content": "a"},
                    {"path": "same.txt", "content": "b"},
                ]
            }
        },
    }

    with pytest.raises(ConfigError, match="more than once"):
        resolve_services(load_catalog(repo.root, section), section)


def test_duplicate_claim_is_rejected_after_another_block_service(repo):
    section = {
        "services": ["first", "duplicate"],
        "service_definitions": {
            "first": {"files": [{"path": "same.txt", "content": "first"}]},
            "duplicate": {
                "files": [
                    {"path": "same.txt", "content": "a"},
                    {"path": "same.txt", "content": "b"},
                ]
            },
        },
    }

    with pytest.raises(ConfigError, match="more than once"):
        resolve_services(load_catalog(repo.root, section), section)


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


def test_content_file_prefers_default_managed_files_path(repo):
    repo.write(".github/managed-files/templates/body.txt", "from-managed-files\n")
    repo.write("templates/body.txt", "from-root\n")
    service = parse_service(
        "tpl",
        {"mode": "file", "files": [{"path": "out.txt", "content_file": "templates/body.txt"}]},
        [repo.root / ".github/managed-files", repo.root],
    )
    assert service.files[0].content == "from-managed-files\n"


def test_load_catalog_uses_custom_managed_files_path(repo):
    repo.write("my-managed/templates/custom.txt", "custom-content\n")
    section = {
        "services": ["custom"],
        "service_definitions": {
            "custom": {
                "mode": "file",
                "files": [{"path": "output.txt", "content_file": "templates/custom.txt"}],
            }
        },
        "managed_files_path": "my-managed",
    }
    catalog = load_catalog(repo.root, section)
    assert catalog["custom"].files[0].content == "custom-content\n"


def test_load_catalog_rejects_invalid_managed_files_path(repo):
    section = {"managed_files_path": "../outside"}
    with pytest.raises(ConfigError):
        load_catalog(repo.root, section)


def test_load_catalog_rejects_managed_files_symlink_escape(repo):
    outside = repo.root.parent / "outside-managed-files"
    outside.mkdir()
    (repo.root / "managed-link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ConfigError, match="resolves outside"):
        load_catalog(repo.root, {"managed_files_path": "managed-link"})


def test_load_catalog_rejects_content_symlink_outside_managed_files(repo):
    repo.write("private.txt", "must not be imported\n")
    template = repo.root / ".github/managed-files/private.txt"
    template.parent.mkdir(parents=True)
    template.symlink_to(repo.root / "private.txt")
    section = {
        "service_definitions": {
            "unsafe": {
                "mode": "file",
                "files": [{"path": "output.txt", "content_file": "private.txt"}],
            }
        }
    }

    with pytest.raises(ConfigError, match="failed to read content_file"):
        load_catalog(repo.root, section)


def test_load_catalog_does_not_fallback_to_repo_root_for_content_file(repo):
    repo.write("templates/custom.txt", "from-root-only\n")
    section = {
        "services": ["custom"],
        "service_definitions": {
            "custom": {
                "mode": "file",
                "files": [{"path": "output.txt", "content_file": "templates/custom.txt"}],
            }
        },
    }
    with pytest.raises(ConfigError):
        load_catalog(repo.root, section)
