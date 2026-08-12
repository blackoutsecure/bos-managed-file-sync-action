"""Reconciliation behaviour for the three service modes."""

from __future__ import annotations

from sync_kit.catalog import parse_service
from sync_kit.engine import SyncEngine


def service(name: str, mode: str, path: str, content: str):
    return parse_service(name, {"mode": mode, "files": [{"path": path, "content": content}]})


def test_block_service_creates_file(repo):
    result = SyncEngine(repo.root).sync([service("common", "block", ".gitignore", "node_modules/")])
    assert result.changed
    assert result.changed_files == [".gitignore"]
    assert "node_modules/" in repo.read(".gitignore")


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


def test_changed_files_are_deduplicated(repo):
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
    result = SyncEngine(repo.root).sync([svc])
    assert result.changed_files == ["a.txt"]


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
