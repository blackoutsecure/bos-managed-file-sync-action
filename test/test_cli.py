"""CLI contract: subcommands, exit codes, and GitHub Actions outputs."""

from __future__ import annotations

import json

from sync_kit.catalog import load_catalog, resolve_services
from sync_kit.cli import EXIT_CONFIG, EXIT_DRIFT, EXIT_OK, main


def test_apply_then_clean_drift_check(repo):
    repo.write_config({"services": ["common", "lf_line_endings"]})
    assert main(["apply", "--root", str(repo.root)]) == EXIT_OK
    assert main(["check", "--root", str(repo.root)]) == EXIT_OK


def test_check_exits_non_zero_on_drift(repo):
    repo.write_config({"services": ["common"]})
    assert main(["check", "--root", str(repo.root)]) == EXIT_DRIFT


def test_apply_fail_on_drift_flag(repo):
    repo.write_config({"services": ["common"]})
    assert main(["apply", "--root", str(repo.root), "--dry-run", "--fail-on-drift"]) == EXIT_DRIFT


def test_dry_run_leaves_repo_untouched(repo):
    repo.write_config({"services": ["common"]})
    assert main(["apply", "--root", str(repo.root), "--dry-run"]) == EXIT_OK
    assert not repo.exists(".gitignore")


def test_no_config_and_no_services_is_a_no_op(repo):
    assert main(["apply", "--root", str(repo.root)]) == EXIT_OK


def test_services_flag_without_config(repo):
    assert main(["apply", "--root", str(repo.root), "--services", "dotfiles"]) == EXIT_OK
    assert repo.exists(".editorconfig")


def test_invalid_config_returns_config_exit_code(repo):
    repo.write("bos-universal-config.json", "{ broken")
    assert main(["apply", "--root", str(repo.root)]) == EXIT_CONFIG


def test_unknown_service_returns_config_exit_code(repo):
    repo.write_config({"services": ["nope"]})
    assert main(["apply", "--root", str(repo.root)]) == EXIT_CONFIG


def test_unterminated_marker_returns_config_exit_code(repo):
    repo.write_config({"services": ["common"]})
    repo.write(".gitignore", "# >>> managed-file-sync:common >>>\nstuff\n")
    assert main(["apply", "--root", str(repo.root)]) == EXIT_CONFIG


def test_services_subcommand_lists_catalog(repo, capsys):
    assert main(["services", "--root", str(repo.root)]) == EXIT_OK
    assert "markdownlint" in capsys.readouterr().out


def test_validate_subcommand(repo, capsys):
    repo.write_config({"services": ["common"]})
    assert main(["validate", "--root", str(repo.root)]) == EXIT_OK
    assert "valid" in capsys.readouterr().out


def test_custom_marker_namespace_from_config(repo):
    repo.write_config({"services": ["common"], "marker_namespace": "bos-automation-hub"})
    assert main(["apply", "--root", str(repo.root)]) == EXIT_OK
    assert "bos-automation-hub:common" in repo.read(".gitignore")


def test_managed_note_from_config(repo):
    repo.write_config({"services": ["common"], "managed_note": "Managed by the hub."})
    assert main(["apply", "--root", str(repo.root)]) == EXIT_OK
    assert "# Managed by the hub." in repo.read(".gitignore")


def test_diff_is_printed_by_default(repo, capsys):
    repo.write_config({"services": ["common"]})
    main(["apply", "--root", str(repo.root), "--dry-run"])
    assert "+node_modules/" in capsys.readouterr().out


def test_no_diff_suppresses_the_diff(repo, capsys):
    repo.write_config({"services": ["common"]})
    main(["apply", "--root", str(repo.root), "--dry-run", "--no-diff"])
    out = capsys.readouterr().out
    assert "+node_modules/" not in out
    assert ".gitignore" in out


def test_dependabot_service_produces_valid_yaml(repo):
    repo.write_config({"services": ["dependabot_actions"]})
    assert main(["apply", "--root", str(repo.root)]) == EXIT_OK
    content = repo.read(".github/dependabot.yml")
    assert content.startswith("version: 2\nupdates:\n")


def test_conflicting_services_return_config_exit_code(repo):
    repo.write_config(
        {
            "services": ["a", "b"],
            "service_definitions": {
                "a": {"mode": "file", "files": [{"path": "x.yml", "content": "a"}]},
                "b": {"mode": "file", "files": [{"path": "x.yml", "content": "b"}]},
            },
        }
    )
    assert main(["apply", "--root", str(repo.root)]) == EXIT_CONFIG


def test_readme_minimal_config_is_valid(repo):
    """The minimal config documented in the README must resolve against marketplace defaults."""
    section = {
        "services": ["common", "lf_line_endings", "dotfiles", "codeowners"],
        "variables": {"owner": "Example Org", "codeowner": "@example-org/platform-team"},
    }
    repo.write_config(section)
    catalog = load_catalog(repo.root, section)
    assert len(resolve_services(catalog, section)) == 4
    assert main(["apply", "--root", str(repo.root)]) == EXIT_OK


def test_github_output_is_written(repo, monkeypatch):
    output_file = repo.root / "gh_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    repo.write_config({"use_marketplace_services": False, "services": ["common"]})

    assert main(["apply", "--root", str(repo.root)]) == EXIT_OK

    content = output_file.read_text(encoding="utf-8")
    assert "changed=true" in content
    assert "changed_count=1" in content
    assert json.dumps([".gitignore"]) in content


def test_global_config_is_ignored_by_default(repo):
    repo.write_config({"services": ["common"]})
    repo.write(
        ".github/blackout-secure-managed-file-sync-global-config.json",
        "{ not json",
    )
    assert main(["apply", "--root", str(repo.root)]) == EXIT_OK


def test_global_config_is_loaded_when_enabled(repo):
    repo.write_config({"services": ["common"]})
    repo.write(
        ".github/blackout-secure-managed-file-sync-global-config.json",
        "{ not json",
    )
    assert main(["apply", "--root", str(repo.root), "--use-global-config"]) == EXIT_CONFIG


def test_cli_managed_files_path_override(repo):
    repo.write(
        ".github/bos-universal-config.json",
        json.dumps(
            {
                "managed_file_sync": {
                    "services": ["custom"],
                    "service_definitions": {
                        "custom": {
                            "mode": "file",
                            "files": [{"path": "MANAGED.txt", "content_file": "templates/custom.txt"}],
                        }
                    },
                }
            }
        ),
    )
    repo.write("templates/custom.txt", "root-template\n")
    repo.write("alt-managed/templates/custom.txt", "managed-template\n")

    assert (
        main(
            [
                "apply",
                "--root",
                str(repo.root),
                "--managed-files-path",
                "alt-managed",
            ]
        )
        == EXIT_OK
    )
    assert repo.read("MANAGED.txt").endswith("managed-template\n")
