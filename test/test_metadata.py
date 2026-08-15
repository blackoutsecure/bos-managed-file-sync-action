from __future__ import annotations

from sync_kit import __version__
from sync_kit.metadata import (
    PACKAGE_NAME,
    RESERVED_METADATA_KEYS,
    package_metadata,
    strip_package_metadata,
)


def test_package_metadata_is_available_without_config():
    metadata = package_metadata()
    assert metadata["name"] == PACKAGE_NAME
    assert metadata["version"]
    assert metadata["author"]
    assert metadata["description"]


def test_package_metadata_includes_official_links_and_legal_identity():
    metadata = package_metadata()

    assert metadata["website"] == "https://blackoutsecure.app"
    assert metadata["repository"] == (
        "https://github.com/blackoutsecure/bos-managed-file-sync-action"
    )
    assert metadata["documentation"] == (
        "https://github.com/blackoutsecure/bos-managed-file-sync-action#readme"
    )
    assert metadata["issues"] == (
        "https://github.com/blackoutsecure/bos-managed-file-sync-action/issues"
    )
    assert metadata["releases"] == (
        "https://github.com/blackoutsecure/bos-managed-file-sync-action/releases"
    )
    assert metadata["marketplace"] == (
        "https://github.com/marketplace/actions/blackout-secure-managed-file-sync"
    )
    assert metadata["author_email"] == "info@blackoutsecure.app"
    assert metadata["support_email"] == "info@blackoutsecure.app"
    assert metadata["license"] == "Apache-2.0"
    assert metadata["copyright"] == "Copyright © 2025-2026 Blackout Secure"


def test_package_metadata_falls_back_to_module_version(monkeypatch):
    import sync_kit.metadata as metadata_mod

    def raise_not_found(_name):
        raise metadata_mod.PackageNotFoundError

    monkeypatch.setattr(metadata_mod, "installed_metadata", raise_not_found)
    assert package_metadata()["version"] == __version__


def test_strip_removes_reserved_keys_only_at_top_level():
    section, ignored = strip_package_metadata(
        {
            "name": "not-the-kit",
            "version": "9.9.9",
            "description": "hijacked",
            "services": ["common"],
            "service_definitions": {"common": {"description": "kept"}},
        }
    )
    assert ignored == ("name", "version", "description")
    assert section == {
        "services": ["common"],
        "service_definitions": {"common": {"description": "kept"}},
    }


def test_strip_is_a_no_op_without_reserved_keys():
    original = {"services": ["common"]}
    section, ignored = strip_package_metadata(original)
    assert ignored == ()
    assert section is original


def test_every_reserved_key_is_stripped():
    section, ignored = strip_package_metadata(dict.fromkeys(RESERVED_METADATA_KEYS, "x"))
    assert section == {}
    assert sorted(ignored) == sorted(RESERVED_METADATA_KEYS)
