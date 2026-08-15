"""Reconciliation behaviour for the three service modes."""

from __future__ import annotations

import os

import pytest

import sync_kit.engine as engine_module
from sync_kit.catalog import parse_service
from sync_kit.engine import SyncEngine
from sync_kit.errors import ConfigError, MarkerError


def service(name: str, mode: str, path: str, content: str):
    return parse_service(name, {"mode": mode, "files": [{"path": path, "content": content}]})


def test_block_service_creates_file(repo):
    result = SyncEngine(repo.root).sync([service("common", "block", ".gitignore", "node_modules/")])
    assert result.changed
    assert result.changed_files == [".gitignore"]
    assert "node_modules/" in repo.read(".gitignore")


def test_block_service_can_adopt_existing_marker_namespace(repo):
    repo.write(
        ".github/dependabot.yml",
        "version: 2\nupdates:\n\n"
        "# >>> bos-automation-hub:dependabot_actions >>>\n"
        "  - package-ecosystem: github-actions\n"
        "# <<< bos-automation-hub:dependabot_actions <<<\n",
    )
    adopted = parse_service(
        "dependabot_actions",
        {
            "mode": "block",
            "files": [
                {
                    "path": ".github/dependabot.yml",
                    "content": "  - package-ecosystem: github-actions\n    directory: /",
                    "marker_namespace": "bos-automation-hub",
                }
            ],
        },
    )

    SyncEngine(repo.root).sync([adopted])

    dependabot = repo.read(".github/dependabot.yml")
    assert dependabot.count("dependabot_actions") == 2
    assert "# >>> managed-file-sync:dependabot_actions >>>" not in dependabot
    assert "directory: /" in dependabot


def test_block_service_rejects_unconfigured_existing_namespace(repo):
    repo.write(
        ".gitattributes",
        "# >>> bos-automation-hub:line_endings >>>\nold\n"
        "# <<< bos-automation-hub:line_endings <<<\n",
    )
    adopted = parse_service(
        "line_endings",
        {
            "mode": "block",
            "files": [{"path": ".gitattributes", "content": "new"}],
        },
    )

    with pytest.raises(ConfigError, match="unmanaged marker namespace"):
        SyncEngine(repo.root).sync([adopted])

    assert "# >>> bos-automation-hub:line_endings >>>" in repo.read(".gitattributes")


def test_block_service_takes_over_existing_namespace_when_enabled(repo):
    repo.write(
        "settings.ini",
        "top=true\n# >>> first:settings >>>\nold\n# <<< first:settings <<<\nbottom=true\n",
    )
    settings = parse_service(
        "settings",
        {"mode": "block", "files": [{"path": "settings.ini", "content": "new"}]},
    )

    SyncEngine(repo.root, take_over_managed_files=True).sync([settings])

    result = repo.read("settings.ini")
    assert "first:settings" not in result
    assert "managed-file-sync:settings" in result
    assert "top=true\n" in result
    assert "bottom=true\n" in result


def test_block_service_rejects_ambiguous_existing_namespaces(repo):
    repo.write(
        "settings.ini",
        "# >>> first:settings >>>\na\n# <<< first:settings <<<\n"
        "# >>> second:settings >>>\nb\n# <<< second:settings <<<\n",
    )
    settings = service("settings", "block", "settings.ini", "new")

    with pytest.raises(ConfigError, match="unmanaged marker namespace"):
        SyncEngine(repo.root).sync([settings])


def test_second_run_is_a_no_op(repo):
    svc = service("common", "block", ".gitignore", "node_modules/")
    SyncEngine(repo.root).sync([svc])
    assert not SyncEngine(repo.root).sync([svc]).changed


def test_file_service_overwrites(repo):
    repo.write("config.json", "{}\n")
    result = SyncEngine(repo.root).sync([service("cfg", "file", "config.json", '{"a": 1}')])
    assert repo.read("config.json") == '{"a": 1}\n'
    assert result.changes[0].action == "updated"


def test_init_service_only_creates_when_missing(repo):
    svc = service("license", "init", "LICENSE", "canonical")
    assert SyncEngine(repo.root).sync([svc]).changes[0].action == "created"

    repo.write("LICENSE", "hand edited\n")
    assert not SyncEngine(repo.root).sync([svc]).changed
    assert repo.read("LICENSE") == "hand edited\n"


def test_init_service_leaves_existing_binary_file_untouched(repo):
    target = repo.root / "artifact.bin"
    target.write_bytes(b"\xff\xfe")

    result = SyncEngine(repo.root).sync([service("artifact", "init", "artifact.bin", "template")])

    assert not result.changed
    assert target.read_bytes() == b"\xff\xfe"


def test_update_service_only_overwrites_existing_file(repo):
    svc = service("workflow", "update", ".github/workflows/sync.yml", "canonical")

    assert not SyncEngine(repo.root).sync([svc]).changed
    assert not repo.exists(".github/workflows/sync.yml")

    repo.write(".github/workflows/sync.yml", "hand edited\n")
    result = SyncEngine(repo.root).sync([svc])

    assert result.changes[0].action == "updated"
    assert repo.read(".github/workflows/sync.yml") == "canonical\n"


def test_dry_run_does_not_write(repo):
    result = SyncEngine(repo.root, dry_run=True).sync([service("cfg", "file", "out.txt", "x")])
    assert result.changed
    assert result.dry_run
    assert not repo.exists("out.txt")


def test_nested_directories_are_created(repo):
    SyncEngine(repo.root).sync([service("dep", "file", ".github/dependabot.yml", "version: 2")])
    assert repo.exists(".github/dependabot.yml")


def test_variables_are_rendered(repo):
    engine = SyncEngine(repo.root, variables={"owner": "acme"})
    engine.sync([service("license", "init", "LICENSE", "Copyright {{owner}}")])
    assert repo.read("LICENSE") == "Copyright acme\n"


def test_content_outside_block_is_preserved(repo):
    repo.write(".gitignore", "local-only\n")
    SyncEngine(repo.root).sync([service("common", "block", ".gitignore", "managed")])
    assert "local-only" in repo.read(".gitignore")


def test_custom_namespace_is_used(repo):
    engine = SyncEngine(repo.root, namespace="bos-automation-hub")
    engine.sync([service("common", "block", ".gitignore", "managed")])
    assert "bos-automation-hub:common" in repo.read(".gitignore")


def test_duplicate_paths_in_one_service_are_rejected(repo):
    svc = parse_service(
        "dup",
        {
            "mode": "block",
            "files": [
                {"path": "a.txt", "content": "one"},
                {"path": "a.txt", "content": "two"},
            ],
        },
    )
    with pytest.raises(ConfigError, match="more than once"):
        SyncEngine(repo.root).sync([svc])


def test_distinct_block_services_share_one_planned_write(repo):
    first = service("first", "block", ".gitignore", "first/")
    second = service("second", "block", ".gitignore", "second/")

    result = SyncEngine(repo.root).sync([first, second])

    assert result.changed_files == [".gitignore"]
    assert "first/" in repo.read(".gitignore")
    assert "second/" in repo.read(".gitignore")
    assert not SyncEngine(repo.root).sync([first, second]).changed


def test_scaffold_is_written_when_file_is_created(repo):
    svc = parse_service(
        "dep",
        {
            "files": [
                {
                    "path": ".github/dependabot.yml",
                    "scaffold": ["version: 2", "updates:"],
                    "content": "  - package-ecosystem: github-actions",
                }
            ]
        },
    )
    SyncEngine(repo.root).sync([svc])
    content = repo.read(".github/dependabot.yml")
    assert content.startswith("version: 2\nupdates:\n")
    assert "package-ecosystem" in content


def test_scaffold_is_not_reapplied_to_existing_file(repo):
    svc = parse_service(
        "dep",
        {"files": [{"path": "dep.yml", "scaffold": "version: 2", "content": "  - x"}]},
    )
    SyncEngine(repo.root).sync([svc])
    SyncEngine(repo.root).sync([svc])
    assert repo.read("dep.yml").count("version: 2") == 1


def test_absent_mode_deletes_the_file(repo):
    repo.write("OLD.md", "retired\n")
    svc = parse_service("retired", {"mode": "absent", "files": [{"path": "OLD.md"}]})
    result = SyncEngine(repo.root).sync([svc])
    assert result.changes[0].action == "deleted"
    assert not repo.exists("OLD.md")


def test_absent_mode_is_a_no_op_when_file_is_missing(repo):
    svc = parse_service("retired", {"mode": "absent", "files": [{"path": "OLD.md"}]})
    assert not SyncEngine(repo.root).sync([svc]).changed


def test_absent_mode_respects_dry_run(repo):
    repo.write("OLD.md", "retired\n")
    svc = parse_service("retired", {"mode": "absent", "files": [{"path": "OLD.md"}]})
    assert SyncEngine(repo.root, dry_run=True).sync([svc]).changed
    assert repo.exists("OLD.md")


def test_absent_mode_deletes_non_utf8_file(repo):
    target = repo.root / "OLD.bin"
    target.write_bytes(b"\xff\xfe")
    svc = parse_service("retired", {"mode": "absent", "files": [{"path": "OLD.bin"}]})

    result = SyncEngine(repo.root).sync([svc])

    assert result.changed
    assert not target.exists()


def test_target_symlink_cannot_modify_file_outside_repo(repo):
    outside = repo.root.parent / "outside-target.txt"
    outside.write_text("keep\n", encoding="utf-8")
    (repo.root / "linked.txt").symlink_to(outside)

    with pytest.raises(ConfigError, match="symbolic link"):
        SyncEngine(repo.root).sync([service("bad", "file", "linked.txt", "overwrite")])

    assert outside.read_text(encoding="utf-8") == "keep\n"


def test_final_symlink_swap_cannot_modify_an_in_repo_file(repo, monkeypatch):
    victim = repo.write("victim.txt", "keep\n")
    original_resolve = engine_module.resolve_inside

    def swap_final_after_check(root, relative_path, *, key):
        if key == "managed path parent":
            (repo.root / "target.txt").symlink_to(victim)
        return original_resolve(root, relative_path, key=key)

    monkeypatch.setattr(engine_module, "resolve_inside", swap_final_after_check)

    with pytest.raises(ConfigError, match="failed to read"):
        SyncEngine(repo.root).sync(
            [service("bad", "file", "target.txt", "overwrite")]
        )

    assert victim.read_text(encoding="utf-8") == "keep\n"


def test_parent_symlink_cannot_write_outside_repo(repo):
    outside = repo.root.parent / "outside-directory"
    outside.mkdir()
    (repo.root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ConfigError, match="resolves outside"):
        SyncEngine(repo.root).sync([service("bad", "file", "linked/file.txt", "overwrite")])

    assert not (outside / "file.txt").exists()


def test_parent_symlink_aliases_are_rejected_before_any_write(repo):
    real = repo.root / "real"
    real.mkdir()
    (repo.root / "alias").symlink_to("real", target_is_directory=True)
    first = service("first", "file", "alias/file.txt", "first")
    second = service("second", "file", "real/file.txt", "second")

    with pytest.raises(ConfigError, match="resolve to the same target"):
        SyncEngine(repo.root).sync([first, second])

    assert not (real / "file.txt").exists()


def test_validation_failure_does_not_apply_earlier_changes(repo):
    repo.write("broken.txt", "# >>> managed-file-sync:broken >>>\nunterminated\n")
    valid = service("valid", "file", "valid.txt", "new")
    broken = service("broken", "block", "broken.txt", "replacement")

    with pytest.raises(MarkerError):
        SyncEngine(repo.root).sync([valid, broken])

    assert not repo.exists("valid.txt")
    assert repo.read("broken.txt").endswith("unterminated\n")


def test_block_sync_preserves_crlf_outside_markers(repo):
    target = repo.root / "config.txt"
    target.write_bytes(
        b"top\r\n# >>> managed-file-sync:common >>>\r\nold\r\n"
        b"# <<< managed-file-sync:common <<<\r\nbottom\r\n"
    )

    SyncEngine(repo.root).sync([service("common", "block", "config.txt", "new")])

    assert target.read_bytes() == (
        b"top\r\n# >>> managed-file-sync:common >>>\r\nnew\r\n"
        b"# <<< managed-file-sync:common <<<\r\nbottom\r\n"
    )


def test_atomic_update_preserves_existing_file_mode(repo):
    target = repo.write("run.sh", "old\n")
    target.chmod(0o755)

    SyncEngine(repo.root).sync([service("script", "file", "run.sh", "new")])

    assert stat_mode(target) == 0o755


def test_created_file_uses_native_umask_and_default_acl_policy(repo, monkeypatch):
    set_umask = os.umask
    previous_umask = set_umask(0o077)
    try:
        probe = repo.root / "permission-probe.txt"
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        os.close(descriptor)

        def reject_process_wide_umask_change(mode):
            raise AssertionError(
                f"sync must not inspect umask by changing it to {mode:#o}"
            )

        monkeypatch.setattr(engine_module.os, "umask", reject_process_wide_umask_change)
        SyncEngine(repo.root).sync([service("private", "file", "private.txt", "secret")])
    finally:
        set_umask(previous_umask)

    assert stat_mode(repo.root / "private.txt") == stat_mode(probe)
    if hasattr(os, "listxattr"):
        assert os.listxattr(repo.root / "private.txt") == os.listxattr(probe)


def test_invalid_utf8_content_is_rejected_before_any_write(repo):
    valid = service("valid", "file", "valid.txt", "new")
    invalid = service("invalid", "file", "invalid.txt", "\ud800")

    with pytest.raises(ConfigError, match="valid UTF-8"):
        SyncEngine(repo.root).sync([valid, invalid])

    assert not repo.exists("valid.txt")
    assert not repo.exists("invalid.txt")


def test_symlink_loop_is_reported_as_config_error(repo):
    (repo.root / "loop").symlink_to("loop")

    with pytest.raises(ConfigError, match="failed to resolve"):
        SyncEngine(repo.root).sync([service("bad", "file", "loop/file.txt", "x")])


def test_concurrent_replacement_is_detected_before_any_write(repo, monkeypatch):
    target = repo.write("existing.txt", "old\n")
    first = service("first", "file", "new.txt", "new")
    second = service("second", "file", "existing.txt", "updated")
    original_assert = SyncEngine._assert_unchanged

    def replace_before_assert(self, path, state):
        if path == "existing.txt":
            replacement = repo.write("replacement.txt", "old\n")
            os.replace(replacement, target)
        return original_assert(self, path, state)

    monkeypatch.setattr(SyncEngine, "_assert_unchanged", replace_before_assert)

    with pytest.raises(ConfigError, match="changed during sync"):
        SyncEngine(repo.root).sync([first, second])

    assert not repo.exists("new.txt")
    assert repo.read("existing.txt") == "old\n"


def test_concurrent_creation_is_not_overwritten(repo, monkeypatch):
    original_write = engine_module._atomic_write_bytes

    def create_competing_file(root, target, content, *, mode, create):
        if create:
            target.write_text("competitor\n", encoding="utf-8")
        return original_write(root, target, content, mode=mode, create=create)

    monkeypatch.setattr(engine_module, "_atomic_write_bytes", create_competing_file)

    with pytest.raises(ConfigError, match="failed to update"):
        SyncEngine(repo.root).sync([service("new", "file", "new.txt", "managed")])

    assert repo.read("new.txt") == "competitor\n"


def test_concurrent_parent_symlink_swap_cannot_redirect_write(repo, monkeypatch):
    parent = repo.root / "managed"
    parent.mkdir()
    outside = repo.root.parent / "outside-raced-directory"
    outside.mkdir()
    original_write = engine_module._atomic_write_bytes

    def swap_parent(root, target, content, *, mode, create):
        parent.rename(repo.root / "original-managed")
        parent.symlink_to(outside, target_is_directory=True)
        return original_write(root, target, content, mode=mode, create=create)

    monkeypatch.setattr(engine_module, "_atomic_write_bytes", swap_parent)

    with pytest.raises(ConfigError, match="failed to update"):
        SyncEngine(repo.root).sync(
            [service("new", "file", "managed/new.txt", "managed")]
        )

    assert not (outside / "new.txt").exists()


def test_concurrent_parent_symlink_swap_cannot_redirect_read(repo, monkeypatch):
    parent = repo.root / "managed"
    parent.mkdir()
    (parent / "file.txt").write_text("inside\n", encoding="utf-8")
    outside = repo.root.parent / "outside-raced-read"
    outside.mkdir()
    (outside / "file.txt").write_text("outside\n", encoding="utf-8")
    original_resolve = engine_module.resolve_inside

    def swap_parent_after_resolve(root, relative_path, *, key):
        target = original_resolve(root, relative_path, key=key)
        parent.rename(repo.root / "original-managed")
        parent.symlink_to(outside, target_is_directory=True)
        return target

    monkeypatch.setattr(engine_module, "resolve_inside", swap_parent_after_resolve)

    with pytest.raises(ConfigError, match="failed to read"):
        SyncEngine(repo.root, dry_run=True).sync(
            [service("managed", "file", "managed/file.txt", "replacement")]
        )


def test_note_is_written_into_blocks(repo):
    engine = SyncEngine(repo.root, note="Managed by the hub.")
    engine.sync([service("common", "block", ".gitignore", "node_modules/")])
    assert "# Managed by the hub." in repo.read(".gitignore")


def test_note_becomes_a_header_for_whole_files(repo):
    engine = SyncEngine(repo.root, note="Managed by the hub.")
    engine.sync([service("script", "file", "run.sh", "#!/usr/bin/env bash\necho hi\n")])
    lines = repo.read("run.sh").splitlines()
    assert lines[0] == "#!/usr/bin/env bash"
    assert lines[1] == "# Managed by the hub."
    assert "overwrites" in lines[2]


def test_header_does_not_join_a_shebang_without_a_trailing_newline(repo):
    engine = SyncEngine(repo.root, note="Managed by the hub.")
    engine.sync([service("script", "file", "run.sh", "#!/usr/bin/env bash")])

    lines = repo.read("run.sh").splitlines()
    assert lines[0] == "#!/usr/bin/env bash"
    assert lines[1] == "# Managed by the hub."


def test_init_header_says_the_file_is_safe_to_edit(repo):
    engine = SyncEngine(repo.root, note="Managed by the hub.")
    engine.sync([service("lic", "init", "LICENSE", "text")])
    assert "safe to customize" in repo.read("LICENSE")


def test_note_is_skipped_for_commentless_formats(repo):
    engine = SyncEngine(repo.root, note="Managed by the hub.")
    engine.sync([service("cfg", "file", "config.json", '{"a": 1}')])
    assert repo.read("config.json") == '{"a": 1}\n'


def test_change_carries_a_unified_diff(repo):
    repo.write("config.json", '{"a": 0}\n')
    result = SyncEngine(repo.root).sync([service("cfg", "file", "config.json", '{"a": 1}')])
    diff = result.changes[0].diff()
    assert '-{"a": 0}' in diff
    assert '+{"a": 1}' in diff


def stat_mode(path):
    return os.stat(path).st_mode & 0o777
