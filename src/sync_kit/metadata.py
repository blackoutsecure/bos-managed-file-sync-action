"""Package identity, independent of repository policy configuration.

Identity (name, version, author, description, legal details, and official
links) is owned by the installed package — never by config. Reserved identity
keys are stripped from every config tier before merging, so a repo, org, or
inline override cannot rebrand or misreport the kit that is actually running.
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
PACKAGE_WEBSITE = "https://blackoutsecure.app"
PACKAGE_REPOSITORY = "https://github.com/blackoutsecure/bos-managed-file-sync-action"
PACKAGE_DOCUMENTATION = f"{PACKAGE_REPOSITORY}#readme"
PACKAGE_ISSUES = f"{PACKAGE_REPOSITORY}/issues"
PACKAGE_RELEASES = f"{PACKAGE_REPOSITORY}/releases"
PACKAGE_MARKETPLACE = "https://github.com/marketplace/actions/blackout-secure-managed-file-sync"
PACKAGE_SUPPORT_EMAIL = "info@blackoutsecure.app"
PACKAGE_LICENSE = "Apache-2.0"
PACKAGE_COPYRIGHT = "Copyright © 2025-2026 Blackout Secure"

# Config keys that describe the package rather than repo policy. Stripped from
# every tier (marketplace, global, repo, inline) before the cascade is merged.
RESERVED_METADATA_KEYS = (
    "author",
    "author_email",
    "copyright",
    "description",
    "documentation",
    "homepage",
    "issues",
    "license",
    "maintainer",
    "maintainer_email",
    "name",
    "package_author",
    "package_copyright",
    "package_description",
    "package_license",
    "package_name",
    "package_repository",
    "package_version",
    "package_website",
    "releases",
    "repository",
    "support_email",
    "version",
    "website",
)


def _identity(*, name: str, version: str, author: str, description: str) -> dict[str, str]:
    return {
        "name": name,
        "title": PACKAGE_TITLE,
        "version": version,
        "author": author,
        "author_email": PACKAGE_SUPPORT_EMAIL,
        "description": description,
        "website": PACKAGE_WEBSITE,
        "repository": PACKAGE_REPOSITORY,
        "documentation": PACKAGE_DOCUMENTATION,
        "issues": PACKAGE_ISSUES,
        "releases": PACKAGE_RELEASES,
        "marketplace": PACKAGE_MARKETPLACE,
        "support_email": PACKAGE_SUPPORT_EMAIL,
        "license": PACKAGE_LICENSE,
        "copyright": PACKAGE_COPYRIGHT,
    }


def package_metadata() -> dict[str, str]:
    """Return package identity without loading any configuration."""
    try:
        installed = installed_metadata(PACKAGE_NAME)
    except PackageNotFoundError:
        return _identity(
            name=PACKAGE_NAME,
            version=__version__,
            author=PACKAGE_AUTHOR,
            description=PACKAGE_DESCRIPTION,
        )

    return _identity(
        name=installed.get("Name") or PACKAGE_NAME,
        version=installed.get("Version") or __version__,
        author=installed.get("Author") or PACKAGE_AUTHOR,
        description=installed.get("Summary") or PACKAGE_DESCRIPTION,
    )


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
