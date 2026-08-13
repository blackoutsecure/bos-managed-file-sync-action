"""Managed-block markers and the comment syntax used to write them.

A managed block is delimited by a marker pair whose namespace defaults to
``managed-file-sync`` and can be overridden per repo::

    # >>> managed-file-sync:common >>>
    ...canonical content...
    # <<< managed-file-sync:common <<<

Only the region between the markers is ever rewritten.
"""

from __future__ import annotations

import re
from pathlib import Path

from .errors import MarkerError

DEFAULT_NAMESPACE = "managed-file-sync"

MARKER_START = "{namespace}:{name}"
FALLBACK_COMMENT_PREFIX = "#"

# Comment syntax by file extension. `open|close` denotes a wrapping style.
COMMENT_PREFIXES: dict[str, str] = {
    ".yml": "#",
    ".yaml": "#",
    ".toml": "#",
    ".ini": "#",
    ".cfg": "#",
    ".conf": "#",
    ".sh": "#",
    ".bash": "#",
    ".zsh": "#",
    ".py": "#",
    ".rb": "#",
    ".pl": "#",
    ".tf": "#",
    ".dockerfile": "#",
    ".env": "#",
    ".js": "//",
    ".ts": "//",
    ".jsonc": "//",
    ".go": "//",
    ".java": "//",
    ".c": "//",
    ".h": "//",
    ".cpp": "//",
    ".cs": "//",
    ".rs": "//",
    ".md": "<!--|-->",
    ".markdown": "<!--|-->",
    ".html": "<!--|-->",
    ".xml": "<!--|-->",
}

# Extensionless (or dot-prefixed) files matched on their exact name.
COMMENT_PREFIXES_BY_NAME: dict[str, str] = {
    ".gitignore": "#",
    ".gitattributes": "#",
    ".editorconfig": "#",
    ".dockerignore": "#",
    ".npmignore": "#",
    ".prettierignore": "#",
    ".shellcheckrc": "#",
    "Dockerfile": "#",
    "Makefile": "#",
    "CODEOWNERS": "#",
}

# Formats with no comment syntax — a managed note would make them unparseable.
COMMENTLESS_SUFFIXES = frozenset({".json", ".lock"})


def comment_prefix_for(path: str) -> str:
    """Pick the comment syntax used to wrap a managed block in ``path``."""
    target = Path(path)
    if target.name in COMMENT_PREFIXES_BY_NAME:
        return COMMENT_PREFIXES_BY_NAME[target.name]
    return COMMENT_PREFIXES.get(target.suffix.lower(), FALLBACK_COMMENT_PREFIX)


def supports_comments(path: str) -> bool:
    """``False`` for formats with no comment syntax, where a note would corrupt the file."""
    return Path(path).suffix.lower() not in COMMENTLESS_SUFFIXES


def comment_lines(text: str, prefix: str) -> list[str]:
    """Render ``text`` as comment lines in the style of ``prefix``."""
    if "|" in prefix:
        open_token, close_token = prefix.split("|", 1)
        return [f"{open_token} {line} {close_token}".rstrip() for line in text.splitlines()]
    return [f"{prefix} {line}".rstrip() for line in text.splitlines()]


def marker_lines(service: str, prefix: str, namespace: str = DEFAULT_NAMESPACE) -> tuple[str, str]:
    """Return the ``(start, end)`` marker lines for a service."""
    tag = MARKER_START.format(namespace=namespace, name=service)
    start, end = f">>> {tag} >>>", f"<<< {tag} <<<"
    if "|" in prefix:
        open_token, close_token = prefix.split("|", 1)
        return f"{open_token} {start} {close_token}", f"{open_token} {end} {close_token}"
    return f"{prefix} {start}", f"{prefix} {end}"


def _is_marker_line(line: str, marker: str) -> bool:
    return line.rstrip("\r\n").strip() == marker.strip()


def find_marker_namespaces(existing: str, service: str) -> set[str]:
    """Find namespaces already used by complete markers for ``service``."""
    identifier = re.escape(service)
    starts = set(
        re.findall(
            rf">>>\s+([A-Za-z0-9_.-]+):{identifier}\s+>>>\s*(?:-->)?\s*$",
            existing,
            re.MULTILINE,
        )
    )
    ends = set(
        re.findall(
            rf"<<<\s+([A-Za-z0-9_.-]+):{identifier}\s+<<<\s*(?:-->)?\s*$",
            existing,
            re.MULTILINE,
        )
    )
    return starts & ends


def render_block(
    service: str,
    content: str,
    prefix: str,
    namespace: str = DEFAULT_NAMESPACE,
    note: str | None = None,
) -> str:
    """Render a complete managed block, markers included.

    ``note`` is written as comment lines directly under the start marker so an
    editor opening the file immediately sees the block is generated.
    """
    start, end = marker_lines(service, prefix, namespace)
    parts = [start]
    if note:
        parts.extend(comment_lines(note, prefix))
    body = content.strip("\r\n")
    if body:
        parts.append(body)
    parts.append(end)
    rendered = "\n".join(parts)
    rendered_lines = rendered.splitlines()
    if (
        sum(_is_marker_line(line, start) for line in rendered_lines) != 1
        or sum(_is_marker_line(line, end) for line in rendered_lines) != 1
    ):
        raise MarkerError(
            f"managed content or note for service '{service}' contains a marker line"
        )
    return rendered


def apply_block(
    existing: str,
    service: str,
    content: str,
    prefix: str,
    namespace: str = DEFAULT_NAMESPACE,
    note: str | None = None,
) -> str:
    """Return ``existing`` with the service's managed block set to ``content``.

    The block is replaced in place when the markers are present and appended
    otherwise. Content outside the markers is preserved byte for byte.
    """
    block = render_block(service, content, prefix, namespace, note)
    lines = existing.splitlines(keepends=True)
    start_marker, end_marker = marker_lines(service, prefix, namespace)
    start_indices = [
        index
        for index, line in enumerate(lines)
        if _is_marker_line(line, start_marker)
    ]
    end_indices = [
        index
        for index, line in enumerate(lines)
        if _is_marker_line(line, end_marker)
    ]

    if not start_indices and not end_indices:
        line_ending = _preferred_line_ending(existing)
        rendered = _use_line_ending(block, line_ending)
        if not existing:
            return rendered + line_ending
        separator = "" if existing.endswith(("\n", "\r")) else line_ending
        return f"{existing}{separator}{line_ending}{rendered}{line_ending}"

    if len(start_indices) != 1 or len(end_indices) != 1:
        raise MarkerError(
            f"managed block for service '{service}' must contain exactly one start marker "
            "and one end marker"
        )
    start_index = start_indices[0]
    end_index = end_indices[0]
    if end_index < start_index:
        raise MarkerError(
            f"managed block for service '{service}' has its end marker before its start marker"
        )

    start_offset = sum(len(line) for line in lines[:start_index])
    end_offset = start_offset + sum(
        len(line) for line in lines[start_index : end_index + 1]
    )
    line_ending = _line_ending(lines[start_index]) or _preferred_line_ending(existing)
    replacement = _use_line_ending(block, line_ending)
    replacement += _line_ending(lines[end_index])
    return existing[:start_offset] + replacement + existing[end_offset:]


def remove_block(existing: str, service: str, namespace: str, prefix: str) -> str:
    """Remove one complete managed block while preserving surrounding text."""
    lines = existing.splitlines(keepends=True)
    start_marker, end_marker = marker_lines(service, prefix, namespace)
    start_indices = [
        index for index, line in enumerate(lines) if _is_marker_line(line, start_marker)
    ]
    end_indices = [
        index for index, line in enumerate(lines) if _is_marker_line(line, end_marker)
    ]
    if len(start_indices) != 1 or len(end_indices) != 1:
        raise MarkerError(
            f"managed block for service '{service}' must contain exactly one start marker "
            "and one end marker"
        )
    start_index = start_indices[0]
    end_index = end_indices[0]
    if end_index < start_index:
        raise MarkerError(
            f"managed block for service '{service}' has its end marker before its start marker"
        )
    start_offset = sum(len(line) for line in lines[:start_index])
    end_offset = start_offset + sum(len(line) for line in lines[start_index : end_index + 1])
    return existing[:start_offset] + existing[end_offset:]


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def _preferred_line_ending(text: str) -> str:
    match = re.search(r"\r\n|\n|\r", text)
    return match.group(0) if match else "\n"


def _use_line_ending(text: str, line_ending: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", line_ending)
