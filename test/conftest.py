"""Shared pytest fixtures for the managed-file sync kit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class Repo:
    """A throwaway repository working tree."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, rel: str, content: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def exists(self, rel: str) -> bool:
        return (self.root / rel).is_file()

    def write_config(self, section: dict, name: str = "bos-universal-config.json") -> Path:
        return self.write(name, json.dumps({"managed_file_sync": section}, indent=2))


@pytest.fixture()
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)
