"""The long-lived objects the web app, the workers and the CLI share."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from .config import Settings
from .db import Database
from .files import ProjectFiles
from .meta import MetaClient


@dataclass
class Services:
    settings: Settings
    db: Database
    _client: MetaClient | None = field(default=None, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @classmethod
    def create(cls, settings: Settings) -> Services:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        return cls(settings=settings, db=Database(settings.data_dir / "storeel.db"))

    def files(self, project_id: str) -> ProjectFiles:
        return ProjectFiles(self.settings.data_dir, project_id)

    @property
    def client(self) -> MetaClient:
        """The Model API client, created on first use (raises ConfigError without a key)."""
        with self._lock:
            if self._client is None:
                self._client = MetaClient(self.settings.require_api_key(), self.settings.api_base)
            return self._client

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None
