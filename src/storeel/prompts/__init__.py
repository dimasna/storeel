"""Model instructions, kept as Markdown files next to this module so they read as prose."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent


@cache
def load_prompt(name: str) -> str:
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


@cache
def load_examples() -> list[dict[str, Any]]:
    """Whole example answers (few-shot), each {"novel", "intro", "script"}."""
    return json.loads((_DIR / "examples.json").read_text(encoding="utf-8"))
