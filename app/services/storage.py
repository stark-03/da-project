"""Private storage for uploaded document images.

Files are written under ``UPLOAD_FOLDER`` (inside ``instance/``, never ``static/``) with random
names. Every path is resolved and confined to the upload folder before use.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path


class StorageError(Exception):
    """A stored file could not be written, read or located."""


class DocumentStorage:
    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).resolve()

    def ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, extension: str) -> str:
        """Write ``data`` under a new random name and return that name (relative path)."""
        self.ensure_root()
        name = f"{secrets.token_hex(16)}.{extension}"
        path = self._resolve(name)
        # "xb" fails rather than overwrite if a name ever collides.
        with open(path, "xb") as handle:
            handle.write(data)
        return name

    def read(self, name: str) -> bytes:
        path = self._resolve(name)
        if not path.is_file():
            raise StorageError("Stored document file is missing.")
        return path.read_bytes()

    def path_for(self, name: str) -> Path:
        path = self._resolve(name)
        if not path.is_file():
            raise StorageError("Stored document file is missing.")
        return path

    def delete(self, name: str | None) -> bool:
        if not name:
            return False
        path = self._resolve(name)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def _resolve(self, name: str) -> Path:
        if not name or Path(name).name != name or name.startswith("."):
            raise StorageError("Invalid stored file name.")
        path = (self.root / name).resolve()
        if path.parent != self.root:
            raise StorageError("Invalid stored file name.")
        return path
