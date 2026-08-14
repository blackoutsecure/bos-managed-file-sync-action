"""Package identity, independent of repository policy configuration.

Identity (name, version, author, description) is owned by the installed
package — never by config. Reserved identity keys are stripped from every
config tier before merging, so a repo, org, or inline override cannot rebrand
or misreport the kit that is actually running.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import metadata as installed_metadata
from typing import Any

from ._version import __version__

PACKAGE_NAME = "bos-managed-file-sync"
PACKAGE_TITLE = "Blackout Secure Managed File Sync"
PACKAGE_AUTHOR = "Blackout Secure"
PACKAGE_DESCRIPTION = (
    "Config-driven managed-file sync — keep canonical repo files and managed "
    "blocks in sync across repositories."
)

# Config keys that describe the package rather than repo policy. Stripped from
# every tier (marketplace, global, repo, inline) before the cascade is merged.
RESERVED_METADATA_KEYS = (
    "author",
    "author_email",
    "description",
    "license",
    "name",
    "package_author",
    "package_description",
    "package_name",
    "package_version",
    "version",
)


def package_metadata() -> dict[str, str]:
    """Return package identity without loading any configuration."""
    try:
        installed = installed_metadata(PACKAGE_NAME)
    except PackageNotFoundError:
        return {
            "name": PACKAGE_NAME,
            "title": PACKAGE_TITLE,
            "version": __version__,
            "author": PACKAGE_AUTHOR,
            "description": PACKAGE_DESCRIPTION,
        }

    return {
        "name": installed.get("Name") or PACKAGE_NAME,
        "title": PACKAGE_TITLE,
        "version": installed.get("Version") or __version__,
        "author": installed.get("Author") or PACKAGE_AUTHOR,
        "description": installed.get("Summary") or PACKAGE_DESCRIPTION,
    }


def strip_package_metadata(
    section: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Drop reserved identity keys from one config section.

    Only the top level of a section is stripped; nested ``service_definitions``
    keep their own ``description`` because that describes policy, not the
    package.

    Returns:
        The cleaned section and the reserved keys that were ignored.
    """
    if not section:
        return section, ()
    ignored = tuple(key for key in section if key in RESERVED_METADATA_KEYS)
    if not ignored:
        return section, ()
    return {key: value for key, value in section.items() if key not in ignored}, ignored
