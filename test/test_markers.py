"""Managed-block marker handling."""

from __future__ import annotations

import pytest

from sync_kit.errors import MarkerError
from sync_kit.markers import (
    apply_block,
    comment_prefix_for,
    dedupe_lines_outside_block,
    marker_lines,
    render_block,
    supports_comments,
)


def test_appends_block_when_markers_absent():
    result = apply_block("existing line\n", "common", "managed\n", "#")
    assert result.startswith("existing line\n")
    assert "# >>> managed-file-sync:common >>>" in result
    assert "# <<< managed-file-sync:common <<<" in result


def test_replaces_block_in_place_and_preserves_surroundings():
    original = (
        "top\n# >>> managed-file-sync:common >>>\nold\n# <<< managed-file-sync:common <<<\nbottom\n"
    )
    result = apply_block(original, "common", "new", "#")
    assert "new" in result
    assert "old" not in result
    assert result.startswith("top\n")
    assert result.endswith("bottom\n")


def test_service_name_does_not_match_a_longer_marker_name():
    original = "# >>> managed-file-sync:foo-bar >>>\nkeep\n# <<< managed-file-sync:foo-bar <<<\n"
    result = apply_block(original, "foo", "new", "#")

    assert "keep" in result
    assert result.count("managed-file-sync:foo-bar") == 2
    assert result.count("managed-file-sync:foo >>>") == 1


def test_replacement_preserves_crlf_outside_the_managed_block():
    original = (
        "top\r\n"
        "# >>> managed-file-sync:common >>>\r\n"
        "old\r\n"
        "# <<< managed-file-sync:common <<<\r\n"
        "bottom\r\n"
    )

    result = apply_block(original, "common", "new", "#")

    assert result == (
        "top\r\n"
        "# >>> managed-file-sync:common >>>\r\n"
        "new\r\n"
        "# <<< managed-file-sync:common <<<\r\n"
        "bottom\r\n"
    )


def test_idempotent():
    once = apply_block("", "common", "value", "#")
    assert apply_block(once, "common", "value", "#") == once


def test_unterminated_block_raises():
    with pytest.raises(MarkerError):
        apply_block("# >>> managed-file-sync:common >>>\nvalue\n", "common", "value", "#")


def test_marker_text_inside_content_does_not_end_block():
    content = "documentation mentions <<< managed-file-sync:common <<< inline"
    once = apply_block("", "common", content, "#")

    assert apply_block(once, "common", content, "#") == once


@pytest.mark.parametrize(
    ("content", "note"),
    [
        ("# <<< managed-file-sync:common <<<", None),
        ("value", ">>> managed-file-sync:common >>>"),
    ],
)
def test_complete_marker_line_in_generated_block_is_rejected(content, note):
    with pytest.raises(MarkerError, match="content or note"):
        apply_block("", "common", content, "#", note=note)


def test_duplicate_complete_markers_are_rejected():
    existing = (
        "# >>> managed-file-sync:common >>>\n"
        "# >>> managed-file-sync:common >>>\n"
        "value\n"
        "# <<< managed-file-sync:common <<<\n"
    )

    with pytest.raises(MarkerError, match="exactly one"):
        apply_block(existing, "common", "new", "#")


def test_orphaned_end_marker_is_rejected():
    with pytest.raises(MarkerError, match="exactly one"):
        apply_block("# <<< managed-file-sync:common <<<\n", "common", "new", "#")


def test_empty_content_still_writes_markers():
    assert render_block("common", "", "#").splitlines() == [
        "# >>> managed-file-sync:common >>>",
        "# <<< managed-file-sync:common <<<",
    ]


def test_markdown_uses_wrapping_comments():
    result = apply_block("", "docs", "text", comment_prefix_for("README.md"))
    assert "<!-- >>> managed-file-sync:docs >>> -->" in result
    assert "<!-- <<< managed-file-sync:docs <<< -->" in result


def test_dedupe_removes_exact_duplicate_line_outside_block():
    existing = apply_block(".venv/\nother-thing\n", "common", "node_modules/\n.venv/", "#")

    result = dedupe_lines_outside_block(existing, "node_modules/\n.venv/", "#")

    assert ".venv/" not in result.split("# >>> managed-file-sync:common >>>")[0]
    assert "other-thing" in result
    assert result.count(".venv/") == 1  # only the copy inside the managed block survives


def test_dedupe_leaves_non_duplicate_lines_untouched():
    existing = apply_block("keep-me\n", "common", "node_modules/", "#")

    result = dedupe_lines_outside_block(existing, "node_modules/", "#")

    assert "keep-me\n" in result


def test_dedupe_never_touches_lines_inside_any_managed_block():
    existing = (
        "# >>> managed-file-sync:other >>>\n"
        "node_modules/\n"
        "# <<< managed-file-sync:other <<<\n"
    )
    existing = apply_block(existing, "common", "unrelated", "#")

    result = dedupe_lines_outside_block(existing, "node_modules/", "#")

    assert "# >>> managed-file-sync:other >>>\nnode_modules/\n" in result


def test_dedupe_ignores_blank_lines():
    existing = apply_block("\n\n", "common", "\nnode_modules/", "#")

    before = dedupe_lines_outside_block(existing, "\nnode_modules/", "#").split(
        "# >>> managed-file-sync:common >>>"
    )[0]

    assert before.strip("\n") == ""
    assert before.count("\n") == existing.split("# >>> managed-file-sync:common >>>")[0].count("\n")


def test_dedupe_is_a_no_op_when_block_content_is_only_blank_lines():
    existing = apply_block("node_modules/\n", "common", "", "#")

    result = dedupe_lines_outside_block(existing, "", "#")

    assert result.startswith("node_modules/\n")


def test_custom_namespace_round_trips():
    start, end = marker_lines("common", "#", "bos-automation-hub")
    original = f"{start}\nold\n{end}\n"
    result = apply_block(original, "common", "new", "#", "bos-automation-hub")
    assert "new" in result
    assert "old" not in result
    assert result.count(">>> bos-automation-hub:common >>>") == 1


def test_other_namespace_blocks_are_untouched():
    hub_block = "# >>> bos-automation-hub:common >>>\nhub\n# <<< bos-automation-hub:common <<<\n"
    result = apply_block(hub_block, "common", "mine", "#")
    assert "hub" in result
    assert "managed-file-sync:common" in result


@pytest.mark.parametrize(
    ("path", "prefix"),
    [
        (".github/workflows/ci.yml", "#"),
        ("src/index.ts", "//"),
        (".gitignore", "#"),
        (".shellcheckrc", "#"),
        ("CODEOWNERS", "#"),
        ("README.md", "<!--|-->"),
        ("unknown.xyz", "#"),
    ],
)
def test_comment_prefix_detection(path, prefix):
    assert comment_prefix_for(path) == prefix


def test_note_is_rendered_under_the_start_marker():
    result = render_block("common", "body", "#", note="Managed by the hub.")
    assert result.splitlines()[1] == "# Managed by the hub."


def test_note_uses_wrapping_comments_in_markdown():
    result = render_block("docs", "body", "<!--|-->", note="Managed by the hub.")
    assert "<!-- Managed by the hub. -->" in result


def test_note_change_is_detected_as_drift():
    without = apply_block("", "common", "body", "#")
    assert apply_block(without, "common", "body", "#", note="New note.") != without


@pytest.mark.parametrize(
    ("path", "expected"),
    [(".gitignore", True), ("a.yml", True), ("a.json", False), ("poetry.lock", False)],
)
def test_commentless_formats_are_detected(path, expected):
    assert supports_comments(path) is expected
