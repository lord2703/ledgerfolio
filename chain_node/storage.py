"""Disk persistence for one node: its chain, mempool and peer list as JSON files.

Writes go to a temporary file first and are then swapped into place, so a crash
mid-write cannot leave a half-written chain behind.
"""

import json
import os
from pathlib import Path


class Storage:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.data_dir / f"{name}.json"

    def load(self, name: str, default=None):
        path = self._path(name)
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def save(self, name: str, data) -> None:
        path = self._path(name)
        temporary = path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)


class MemoryStorage:
    """Keeps everything in memory. Used by tests."""

    def __init__(self):
        self._data = {}

    def load(self, name: str, default=None):
        return json.loads(self._data[name]) if name in self._data else default

    def save(self, name: str, data) -> None:
        self._data[name] = json.dumps(data)
