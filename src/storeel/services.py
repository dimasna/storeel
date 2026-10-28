"""The long-lived objects the web app, the workers and the CLI share."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

import httpx

from .config import Settings
from .db import Database
from .files import ProjectFiles
from .meta import MetaClient

API_KEY = re.compile(r"^[\x21-\x7e]{8,512}$")  # printable ASCII, no spaces (Meta keys look like "LLM|...")


class KeyVault:
    """Users' Model API keys, held in memory for their queued and running jobs.

    Each user brings their own key. It arrives with the request that starts a job, stays
    here until the job ends, and is never written to the database, the logs or the disk: a
    restart forgets every key (and fails the jobs that were waiting for one).
    """

    def __init__(self) -> None:
        self._keys: dict[str, str] = {}
        self._lock = threading.Lock()

    def put(self, job_id: str, key: str) -> None:
        with self._lock:
            self._keys[job_id] = key

    def get(self, job_id: str) -> str | None:
        with self._lock:
            return self._keys.get(job_id)

    def drop(self, job_id: str) -> None:
        with self._lock:
            self._keys.pop(job_id, None)


def valid_key(value: str | None) -> str | None:
    """The key, stripped, if it looks like one; None otherwise."""
    key = (value or "").strip()
    return key if API_KEY.match(key) else None


@dataclass
class Services:
    settings: Settings
    db: Database
    keys: KeyVault = field(default_factory=KeyVault)
    transport: httpx.BaseTransport | None = None  # set only by tests and local harnesses

    @classmethod
    def create(cls, settings: Settings) -> Services:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        return cls(settings=settings, db=Database(settings.data_dir / "storeel.db"))

    def files(self, project_id: str) -> ProjectFiles:
        return ProjectFiles(self.settings.data_dir, project_id)

    def novel_files(self, novel_id: str) -> ProjectFiles:
        """A novel's own media: the character bible's portraits and recurring props."""
        return ProjectFiles(self.settings.data_dir, novel_id, area="novels")

    def client(self, api_key: str, *, max_attempts: int = 4) -> MetaClient:
        """A Model API client for one user's key (the caller closes it)."""
        base = self.settings.api_base
        return MetaClient(api_key, base, max_attempts=max_attempts, transport=self.transport)
