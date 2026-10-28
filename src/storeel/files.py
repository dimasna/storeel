"""Where a project's media lives.

Files are addressed by keys relative to the project's folder ("uploads/3f2a.mp4"), never by
absolute paths, so the database stays portable and the storage can move (for example to
object storage) without rewriting projects. Keys are validated before they touch the disk.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

PROJECT_ID = re.compile(r"^[0-9a-f]{32}$")
KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}(/[A-Za-z0-9][A-Za-z0-9._-]{0,120}){0,4}$")


class ProjectFiles:
    """A project's (or, with `area="novels"`, a novel's) folder of media."""

    def __init__(self, data_dir: Path, project_id: str, area: str = "projects") -> None:
        if not PROJECT_ID.match(project_id):
            raise ValueError(f"invalid project id {project_id!r}")
        if area not in ("projects", "novels"):
            raise ValueError(f"invalid storage area {area!r}")
        self.root = (data_dir / area / project_id).resolve()

    def path(self, key: str) -> Path:
        """The file for `key`; rejects anything that could point outside the project folder."""
        if not KEY.match(key):
            raise ValueError(f"invalid file key {key!r}")
        path = self.root / key
        if not path.resolve().is_relative_to(self.root):
            raise ValueError(f"invalid file key {key!r}")
        return path

    def prepare(self, key: str) -> Path:
        """The path for a file about to be written, with its folder created."""
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def exists(self, key: str | None) -> bool:
        return bool(key) and self.path(key).is_file()

    def write_bytes(self, key: str, data: bytes) -> Path:
        """Write atomically: readers never see a half-written file."""
        path = self.prepare(key)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return path

    def delete(self, key: str | None) -> None:
        if key:
            self.path(key).unlink(missing_ok=True)

    def remove_all(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
