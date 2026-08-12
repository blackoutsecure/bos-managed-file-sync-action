"""Managed-block marker handling."""

from __future__ import annotations

import pytest

from sync_kit.errors import MarkerError
from sync_kit.markers import (
    apply_block,
    comment_prefix_for,
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
        "top\n"
        "# >>> managed-file-sync:common >>>\n"
        "old\n"
        "# <<< managed-file-sync:common <<<\n"
        "bottom\n"
    )
    result = apply_block(original, "common", "new", "#")
    assert "new" in result
    assert "old" not in result
    assert result.startswith("top\n")
    assert result.endswith("bottom\n")


def test_idempotent():
    once = apply_block("", "common", "value", "#")
    assert apply_block(once, "common", "value", "#") == once


def test_unterminated_block_raises():
    with pytest.raises(MarkerError):
        apply_block("# >>> managed-file-sync:common >>>\nvalue\n", "common", "value", "#")


def test_empty_content_still_writes_markers():
    assert render_block("common", "", "#").splitlines() == [
        "# >>> managed-file-sync:common >>>",
        "# <<< managed-file-sync:common <<<",
    ]


def test_markdown_uses_wrapping_comments():
    result = apply_block("", "docs", "text", comment_prefix_for("README.md"))
    assert "<!-- >>> managed-file-sync:docs >>> -->" in result
    assert "<!-- <<< managed-file-sync:docs <<< -->" in result


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
