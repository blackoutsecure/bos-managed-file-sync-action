"""CLI contract: subcommands, exit codes, and GitHub Actions outputs."""

from __future__ import annotations

import json

from sync_kit.ai import AIRecommendation
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
    assert main(["apply", "--root", str(repo.root), "--services", "editorconfig"]) == EXIT_OK
    assert repo.exists(".editorconfig")


def test_editorconfig_service_preserves_custom_content(repo):
    repo.write(
        ".editorconfig",
        "root = true\n\n[*.toml]\nindent_size = 2\n",
    )

    assert main(["apply", "--root", str(repo.root), "--services", "editorconfig"]) == EXIT_OK

    editorconfig = repo.read(".editorconfig")
    assert "[*.toml]\nindent_size = 2" in editorconfig
    assert "# >>> managed-file-sync:editorconfig >>>" in editorconfig
    assert "[*]\ncharset = utf-8" in editorconfig


def test_managed_file_sync_workflow_service_updates_the_invoking_workflow(repo):
    repo.write(
        ".github/blackout-secure-managed-file-sync-global-config.json",
        json.dumps(
            {
                "managed_file_sync": {
                    "service_definitions": {
                        "managed_file_sync_workflow": {
                            "mode": "update",
                            "files": [
                                {
                                    "path": ".github/workflows/managed-file-sync.yml",
                                    "content_lines": [
                                        "name: Managed file sync",
                                        "",
                                        "jobs:",
                                        "  sync:",
                                        "    runs-on: {{SELECTED_RUNNER}}",
                                        "    steps:",
                                        "      - uses: blackoutsecure/bos-managed-file-sync-action@v1",
                                    ],
                                }
                            ],
                        }
                    }
                }
            }
        ),
    )
    repo.write(".github/workflows/managed-file-sync.yml", "name: local workflow\n")
    assert (
        main(
            [
                "apply",
                "--root",
                str(repo.root),
                "--services",
                "managed_file_sync_workflow",
            ]
        )
        == EXIT_OK
    )
    workflow = repo.read(".github/workflows/managed-file-sync.yml")
    assert "runs-on: ubuntu-latest" in workflow
    assert "uses: blackoutsecure/bos-managed-file-sync-action@v1" in workflow


def test_config_json_argument_overrides_file_based_config(repo):
    assert (
        main(
            [
                "apply",
                "--root",
                str(repo.root),
                "--config-json",
                '{"managed_file_sync":{"services":["common"]}}',
            ]
        )
        == EXIT_OK
    )
    assert repo.exists(".gitignore")


def test_global_config_json_argument_overrides_file_based_global_config(repo):
    repo.write(
        ".github/blackout-secure-managed-file-sync-global-config.json",
        '{"managed_file_sync":{"services":["editorconfig"]}}',
    )

    assert (
        main(
            [
                "apply",
                "--root",
                str(repo.root),
                "--global-config-json",
                '{"managed_file_sync":{"services":["common"]}}',
            ]
        )
        == EXIT_OK
    )
    assert repo.exists(".gitignore")


def test_global_config_json_can_update_an_existing_inline_workflow_service(repo):
    repo.write(".github/workflows/bos-universal-sync-kicker.yml", "name: local sync\n")

    assert (
        main(
            [
                "apply",
                "--root",
                str(repo.root),
                "--global-config-json",
                json.dumps(
                    {
                        "managed_file_sync": {
                            "use_marketplace_config": False,
                            "services": ["bos_universal_sync_kicker"],
                            "service_definitions": {
                                "bos_universal_sync_kicker": {
                                    "mode": "update",
                                    "files": [
                                        {
                                            "path": ".github/workflows/bos-universal-sync-kicker.yml",
                                            "content_lines": ["name: Canonical sync"],
                                        }
                                    ],
                                }
                            },
                        }
                    }
                ),
            ]
        )
        == EXIT_OK
    )
    assert repo.read(".github/workflows/bos-universal-sync-kicker.yml") == "name: Canonical sync\n"


def test_invalid_config_returns_config_exit_code(repo):
    repo.write("bos-universal-config.json", "{ broken")
    assert main(["apply", "--root", str(repo.root)]) == EXIT_CONFIG


def test_missing_service_definition_writes_detailed_error_summary(repo, capsys, monkeypatch):
    summary_file = repo.root / "gh_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    repo.write_config(
        {
            "services": ["nope"],
            "ai": {"enable_ai_error_remediation": False},
        }
    )

    assert main(["apply", "--root", str(repo.root)]) == EXIT_CONFIG
    error = capsys.readouterr().err
    summary = summary_file.read_text(encoding="utf-8")

    assert error.startswith("::error::managed-file-sync config error: ")
    assert "missing service definition schema(s)" in error
    assert "managed_file_sync.service_definitions.nope" in error
    assert "# Blackout Secure Managed File Sync Report" in summary
    assert "## Executive summary" in summary
    assert "**Verdict:** Critical configuration error" in summary
    assert "## Configuration used" in summary
    assert "## Errors requiring attention" in summary
    assert "| `MFS-CFG-004` | Critical |" in summary
    assert "managed_file_sync.service_definitions.nope" in summary
    assert "## Recommendations" in summary
    assert "Blackout Secure Recommended Remediation" in summary
    assert "High (deterministic)" in summary
    assert "AI-assisted remediation" in summary
    assert "disabled by policy" in summary
    assert "## Scope and methodology" in summary


def test_failure_summary_adds_ai_remediation_when_provider_is_available(
    repo, monkeypatch
):
    summary_file = repo.root / "gh_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    repo.write_config({"services": ["nope"]})
    captured: dict = {}

    def fake_recommend_error(finding, provider):
        captured["finding"] = finding
        captured["provider"] = provider
        return AIRecommendation(
            recommendation="Define the missing service in the repository policy.",
            rationale="The service was selected but no matching definition was merged.",
            confidence="Medium",
        )

    monkeypatch.setattr("sync_kit.cli.recommend_error", fake_recommend_error)

    assert main(["apply", "--root", str(repo.root)]) == EXIT_CONFIG
    summary = summary_file.read_text(encoding="utf-8")

    assert set(captured["finding"]) == {
        "category",
        "error_text",
        "location",
        "deterministic_remediation",
    }
    assert captured["provider"].name == "github-models"
    assert "generated by github-models" in summary
    assert "Define the missing service in the repository policy." in summary
    assert "Medium (AI-assessed)" in summary
    assert "github-models / openai/gpt-4o-mini" in summary
    assert "High (deterministic)" in summary


def test_invalid_json_report_does_not_call_ai_when_policy_cannot_be_resolved(
    repo, monkeypatch
):
    summary_file = repo.root / "gh_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    repo.write("bos-universal-config.json", "{ broken")

    def unexpected_ai_call(*_args, **_kwargs):
        raise AssertionError("AI must not run when repository policy cannot be parsed")

    monkeypatch.setattr("sync_kit.cli.recommend_error", unexpected_ai_call)

    assert main(["apply", "--root", str(repo.root)]) == EXIT_CONFIG
    summary = summary_file.read_text(encoding="utf-8")

    assert "`MFS-CFG-001`" in summary
    assert "Invalid configuration JSON" in summary
    assert "AI policy could not be safely resolved" in summary
    assert "High (deterministic)" in summary


def test_failure_summary_falls_back_when_ai_provider_fails(repo, monkeypatch):
    summary_file = repo.root / "gh_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr("sync_kit.cli.recommend_error", lambda *_args, **_kwargs: None)
    repo.write_config({"services": ["nope"]})

    assert main(["apply", "--root", str(repo.root)]) == EXIT_CONFIG
    summary = summary_file.read_text(encoding="utf-8")

    assert "unavailable (github-models); deterministic fallback" in summary
    assert "Blackout Secure Recommended Remediation" in summary
    assert "High (deterministic)" in summary


def test_failure_summary_write_error_does_not_mask_original_error(repo, monkeypatch, capsys):
    summary_directory = repo.root / "summary-directory"
    summary_directory.mkdir()
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_directory))
    repo.write_config(
        {
            "services": ["nope"],
            "ai": {"enable_ai_error_remediation": False},
        }
    )

    assert main(["apply", "--root", str(repo.root)]) == EXIT_CONFIG
    error = capsys.readouterr().err

    assert "managed-file-sync config error" in error
    assert "managed_file_sync.service_definitions.nope" in error


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
    output = capsys.readouterr().out
    assert "direction: source-to-destination" in output
    assert "valid" in output


def test_reverse_direction_returns_config_exit_code(repo):
    repo.write_config({"direction": "destination-to-source", "services": ["common"]})
    assert main(["validate", "--root", str(repo.root)]) == EXIT_CONFIG


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
        "services": ["common", "lf_line_endings", "editorconfig"],
        "variables": {"owner": "Example Org"},
    }
    repo.write_config(section)
    catalog = load_catalog(repo.root, section)
    assert len(resolve_services(catalog, section)) == 3
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


def test_github_output_delimiter_cannot_collide_with_changed_path(repo, monkeypatch):
    output_file = repo.root / "gh_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    repo.write_config(
        {
            "use_marketplace_services": False,
            "services": ["custom"],
            "service_definitions": {
                "custom": {"mode": "file", "files": [{"path": "MFS_EOF", "content": "x"}]}
            },
        }
    )

    assert main(["apply", "--root", str(repo.root)]) == EXIT_OK

    content = output_file.read_text(encoding="utf-8")
    assert "changed_files<<MFS_EOF_\n" in content
    assert "\nMFS_EOF\nMFS_EOF_\n" in content


def test_github_output_write_failure_returns_config_exit_code(repo, monkeypatch):
    output_directory = repo.root / "output-directory"
    output_directory.mkdir()
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_directory))
    repo.write_config({"services": ["common"]})

    assert main(["apply", "--root", str(repo.root), "--dry-run"]) == EXIT_CONFIG


def test_github_summary_reports_file_and_service_results(repo, monkeypatch):
    summary_file = repo.root / "gh_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    repo.write_config(
        {
            "use_marketplace_config": False,
            "services": ["clean", "drifted"],
            "service_definitions": {
                "clean": {"mode": "file", "files": [{"path": "clean.txt", "content": "ok"}]},
                "drifted": {"mode": "file", "files": [{"path": "drifted.txt", "content": "new"}]},
            },
        }
    )
    repo.write("clean.txt", "ok\n")

    assert main(["apply", "--root", str(repo.root), "--dry-run"]) == EXIT_OK

    summary = summary_file.read_text(encoding="utf-8")
    assert "## Managed file sync: changes pending" in summary
    assert "| 1 | 1 | 2 | 1 |" in summary
    assert "| Action | Count |" in summary
    assert "| Already compliant | 1 |" in summary
    assert "| Created | 1 |" in summary
    assert "| Compliant | Pending | Evaluated files | Changed files |" in summary
    assert "<code>clean</code> | 1 | 0 | 0" in summary
    assert "<code>drifted</code> | 0 | 1 | 1" in summary
    assert "| **Total** | 1 | 1 | 1 |" in summary
    assert "| Compliant | <code>clean.txt</code> | <code>clean</code> | Already compliant |" in summary
    assert "| Pending | <code>drifted.txt</code> | <code>drifted</code> | Created |" in summary
    assert "### Review recommendations" in summary
    assert "### Full config review" in summary


def test_github_summary_omits_absent_states(repo, monkeypatch):
    summary_file = repo.root / "gh_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    repo.write_config(
        {
            "use_marketplace_config": False,
            "services": ["clean"],
            "service_definitions": {
                "clean": {"mode": "file", "files": [{"path": "clean.txt", "content": "ok"}]},
            },
        }
    )
    repo.write("clean.txt", "ok\n")

    assert main(["apply", "--root", str(repo.root)]) == EXIT_OK

    summary = summary_file.read_text(encoding="utf-8")
    assert "| Compliant | Evaluated files | Changed files |" in summary
    assert "| Pending |" not in summary
    assert "| Applied |" not in summary
    assert "| Already compliant | 1 |" in summary
    assert "| Created |" not in summary


def test_github_summary_distinguishes_disabled_services_from_compliance(repo, monkeypatch):
    summary_file = repo.root / "gh_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    repo.write_config(
        {
            "use_marketplace_config": False,
            "services": ["common"],
            "disabled_services": ["common"],
        }
    )

    assert main(["apply", "--root", str(repo.root)]) == EXIT_OK

    summary = summary_file.read_text(encoding="utf-8")
    assert "## Managed file sync: filtered" in summary
    assert "No active managed files were evaluated; configured services were excluded or disabled." in summary
    assert "### Service selection" in summary
    assert "| Requested | <code>common</code> |" in summary
    assert "| Resolved | <code>(none)</code> |" in summary
    assert "| Disabled | <code>common</code> |" in summary
    assert "| Compliant |" not in summary
    assert "### Action breakdown" not in summary


def test_github_summary_includes_config_details(repo, monkeypatch):
    summary_file = repo.root / "gh_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    repo.write_config(
        {
            "use_marketplace_config": True,
            "security": {"enable_python_lint": True, "python_version": "3.12"},
            "services": ["common", "editorconfig"],
            "exclude_services": ["markdownlint"],
            "disabled_services": ["dependabot_actions"],
            "marketplace": {
                "allowlist_paths": ["action.yml", "src"],
                "blocked_paths": [".github/workflows/", "test/"],
                "required_paths": ["action.yml", "src"],
                "repo_metadata": {"enable": True, "homepage": "https://example.com"},
            },
        }
    )

    assert main(["apply", "--root", str(repo.root), "--dry-run"]) == EXIT_OK

    summary = summary_file.read_text(encoding="utf-8")
    assert "### Service selection" in summary
    assert "| Excluded | <code>markdownlint</code> |" in summary
    assert "| Disabled | <code>dependabot_actions</code> |" in summary
    assert "| Allowlist paths | <code>action.yml, src</code> |" in summary
    assert "| Blocked paths | <code>.github/workflows/, test/</code> |" in summary
    assert "| Required paths | <code>action.yml, src</code> |" in summary
    assert "| Repo metadata | <code>enabled</code> |" in summary
    assert "### Full config review" in summary
    assert "<code>marketplace.allowlist_paths</code> | <code>action.yml, src</code> |" in summary
    assert "<code>security.enable_python_lint</code> | <code>True</code> |" in summary
    assert "<code>recommended_toolchain.python.default_version</code> | <code>3.12</code> |" in summary
    assert "<code>recommended_toolchain.dependencies.runtime</code> | <code>(none)</code> |" in summary
    assert "<code>general.action_test.python_versions</code> | <code>3.10, 3.11, 3.12</code> |" in summary
    assert "Recommended Python is 3.12 (&gt;=3.10); tested versions: 3.10, 3.11, 3.12." in summary
    assert "Recommended dependency policy: runtime (none); development pytest&gt;=8.0, ruff&gt;=0.6, PyYAML&gt;=6.0." in summary
    assert "<code>take_over_managed_files</code> | <code>False</code> |" in summary
    assert "### Block policy" in summary
    assert "| <code>common</code> | <code>.gitignore</code> | <code>block</code> |" in summary


def test_global_config_is_loaded_automatically(repo):
    repo.write_config({"services": ["common"]})
    repo.write(
        ".github/blackout-secure-managed-file-sync-global-config.json",
        "{ not json",
    )
    assert main(["apply", "--root", str(repo.root)]) == EXIT_CONFIG


def test_global_config_can_be_disabled(repo):
    repo.write_config({"services": ["common"]})
    repo.write(
        ".github/blackout-secure-managed-file-sync-global-config.json",
        "{ not json",
    )
    assert main(["apply", "--root", str(repo.root), "--no-global-config"]) == EXIT_OK


def test_global_config_is_loaded_when_enabled(repo):
    repo.write_config({"services": ["common"]})
    repo.write(
        ".github/blackout-secure-managed-file-sync-global-config.json",
        "{ not json",
    )
    assert main(["apply", "--root", str(repo.root), "--use-global-config"]) == EXIT_CONFIG


def test_required_global_config_must_exist(repo):
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


def test_configured_managed_files_path_is_used_without_cli_override(repo):
    repo.write(
        ".github/bos-universal-config.json",
        json.dumps(
            {
                "managed_file_sync": {
                    "use_marketplace_services": False,
                    "managed_files_path": "repo-managed",
                    "services": ["custom"],
                    "service_definitions": {
                        "custom": {
                            "mode": "file",
                            "files": [
                                {"path": "MANAGED.txt", "content_file": "templates/custom.txt"}
                            ],
                        }
                    },
                }
            }
        ),
    )
    repo.write("repo-managed/templates/custom.txt", "configured-template\n")

    assert main(["apply", "--root", str(repo.root)]) == EXIT_OK
    assert repo.read("MANAGED.txt").endswith("configured-template\n")


def test_validate_reports_package_identity_and_ignored_keys(repo, capsys):
    repo.write_config({"name": "evil-kit", "version": "9.9.9", "services": ["common"]})

    assert main(["validate", "--root", str(repo.root)]) == EXIT_OK

    output = capsys.readouterr().out
    assert "name:        bos-managed-file-sync" in output
    assert "9.9.9" not in output
    assert "Ignored reserved package metadata keys: name, version" in output
    assert "Config cascade:" in output


def test_summary_reports_package_and_drift_without_ai(repo, tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_MODELS_TOKEN", raising=False)
    repo.write_config({"services": ["common"], "ai": {"enable_ai_drift_summary": False}})

    assert main(["apply", "--root", str(repo.root), "--dry-run"]) == EXIT_OK

    written = summary.read_text(encoding="utf-8")
    assert "### Package" in written
    assert "bos-managed-file-sync" in written
    assert "### Drift summary (local)" in written
    assert "**Confidence:** High (deterministic)" in written
    assert "**Source:** Blackout Secure deterministic rules" in written


def test_summary_reports_ai_drift_provider_and_confidence(repo, tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(
        "sync_kit.cli.summarize",
        lambda _changes, _provider: "- The common service would update one managed file.",
    )
    repo.write_config({"services": ["common"]})

    assert main(["apply", "--root", str(repo.root), "--dry-run"]) == EXIT_OK

    written = summary.read_text(encoding="utf-8")
    assert "### Drift summary (github-models)" in written
    assert "**Confidence:** Medium (AI-generated advisory)" in written
    assert "**Source:** github-models / openai/gpt-4o-mini" in written
