"""Model instructions, kept as Markdown files next to this module so they read as prose."""

from __future__ import annotations

from functools import cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@cache
def load_prompt(name: str) -> str:
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
