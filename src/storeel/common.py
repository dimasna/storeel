"""Small helpers shared across the app."""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime

CancelCheck = Callable[[], bool]


class Cancelled(Exception):
    """The user cancelled the job while it was running."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def digest(*parts: object) -> str:
    """A short, stable content hash of `parts` (bytes are hashed, anything else is JSON-encoded)."""
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, bytes | bytearray | memoryview):
            h.update(b"b")
            h.update(hashlib.sha256(part).digest())
        else:
            h.update(b"j")
            h.update(json.dumps(part, sort_keys=True, ensure_ascii=False, default=str).encode())
    return h.hexdigest()[:16]


def slug(text: str, fallback: str = "item", max_length: int = 40) -> str:
    """Lowercase ASCII snake_case, for ids derived from model output."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")[:max_length].strip("_")
    return value or fallback


def sleep_unless_cancelled(seconds: float, cancel: CancelCheck | None) -> None:
    """Sleep, waking up early (with Cancelled) when the job is cancelled."""
    deadline = time.monotonic() + seconds
    while True:
        if cancel is not None and cancel():
            raise Cancelled
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.25, remaining))
