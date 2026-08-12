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
    name = Path(path).name
    if name in COMMENT_PREFIXES_BY_NAME:
        return COMMENT_PREFIXES_BY_NAME[name]
    return COMMENT_PREFIXES.get(Path(path).suffix.lower(), FALLBACK_COMMENT_PREFIX)


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


def _marker_pattern(service: str, namespace: str, kind: str) -> re.Pattern[str]:
    token = ">>>" if kind == "start" else "<<<"
    return re.compile(rf"{re.escape(token)}\s*{re.escape(namespace)}:{re.escape(service)}\b")


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
    body = content.strip("\n")
    if body:
        parts.append(body)
    parts.append(end)
    return "\n".join(parts)


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
    lines = existing.splitlines()
    start_re = _marker_pattern(service, namespace, "start")
    end_re = _marker_pattern(service, namespace, "end")

    start_index = next((i for i, line in enumerate(lines) if start_re.search(line)), None)
    if start_index is None:
        if not existing.strip():
            return block + "\n"
        separator = "" if existing.endswith("\n") else "\n"
        return f"{existing}{separator}\n{block}\n"

    end_index = next(
        (i for i in range(start_index + 1, len(lines)) if end_re.search(lines[i])),
        None,
    )
    if end_index is None:
        raise MarkerError(
            f"unterminated managed block for service '{service}': found the start marker "
            f"but no '<<< {namespace}:{service}' end marker"
        )

    return "\n".join(lines[:start_index] + block.splitlines() + lines[end_index + 1 :]) + "\n"
