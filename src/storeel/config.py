"""Settings, read from the environment and an optional .env file in the working directory."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")
SERVED_HOSTS = ("localhost", "127.0.0.1")  # Host headers the local server answers
TEXT_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
IMAGE_REASONING = ("low", "high")
ID_RE = re.compile(r"^[0-9a-f]{32}$")  # a reel's or a novel's id


class ConfigError(RuntimeError):
    """A required setting is missing or invalid."""


def _get(name: str, default: str) -> str:
    # An empty value (a `KEY=` placeholder) counts as unset, so it never shadows the default.
    value = os.environ.get(name, "").strip()
    return value or default


def _get_int(name: str, default: int, minimum: int = 1) -> int:
    raw = _get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}")
    return value


def _get_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    value = _get(name, default)
    if value not in choices:
        raise ConfigError(f"{name} must be one of {', '.join(choices)}, got {value!r}")
    return value


def _get_flag(name: str) -> bool:
    value = _get(name, "0").lower()
    if value not in ("0", "1", "true", "false", "yes", "no", "on", "off"):
        raise ConfigError(f"{name} must be 1 or 0, got {value!r}")
    return value in ("1", "true", "yes", "on")


def _get_ids(name: str) -> frozenset[str]:
    ids = frozenset(x.strip() for x in _get(name, "").split(",") if x.strip())
    wrong = sorted(x for x in ids if not ID_RE.match(x))
    if wrong:
        raise ConfigError(f"{name} holds reel or novel ids (32 hex characters), got {', '.join(wrong)}")
    return ids


def _get_hours(name: str) -> float:
    raw = _get(name, "0")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number of hours, got {raw!r}") from exc
    if value < 0:
        raise ConfigError(f"{name} must be 0 (keep everything) or more, got {value}")
    return value


def _api_base(raw: str) -> str:
    url = raw.rstrip("/")
    parts = urlsplit(url)
    # The API key travels in a header on every request: refuse plain HTTP except to this machine.
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in LOCAL_HOSTS):
        raise ConfigError(f"META_API_BASE_URL must use https, got {raw!r}")
    return url


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_base: str
    data_dir: Path
    # The text models: one writes the scripts, one watches the video and plans the pictures.
    script_model: str
    script_effort: str
    # A novel part is written while its creator waits in the chat: at effort "high" Muse Spark
    # answers in about 45 s, while "max" took many minutes and at times never finished.
    part_effort: str
    plan_model: str
    plan_effort: str
    max_output_tokens: int  # per text-model call, reasoning included: bounds a runaway answer
    # Checks: a text model looks at each new character portrait (redrawing a wrong one) and
    # reviews a new part's storyboard against the chapter; "off" skips a check.
    check_model: str
    picture_check_effort: str
    story_review_effort: str
    # The editing agent in the studio's chat: it turns a request into caption, picture and
    # style edits, so a fast model at low effort is enough.
    agent_model: str
    agent_effort: str
    image_model: str
    image_reasoning: str
    image_parallel: int
    asr_model: str
    sam_model: str
    max_input_seconds: int
    max_upload_mb: int
    workers: int
    allowed_hosts: tuple[str, ...]
    # Hosting: each browser sees only the reels and novels it made (no login: an id in a cookie).
    private_projects: bool
    # Reels and novels anyone may watch and none may change, kept by the cleanup (ids).
    showcase: frozenset[str]
    # Delete reels and novels untouched for this many hours (0: keep everything).
    ttl_hours: float

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def require_api_key(self) -> str:
        if not self.api_key:
            raise ConfigError("MODEL_API_KEY is not set. Copy .env.example to .env and add your key.")
        return self.api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(Path.cwd() / ".env", override=False)
    extra_hosts = tuple(h.strip() for h in _get("STOREEL_ALLOWED_HOSTS", "").split(",") if h.strip())
    return Settings(
        api_key=_get("MODEL_API_KEY", ""),
        api_base=_api_base(_get("META_API_BASE_URL", "https://api.meta.ai/v1")),
        data_dir=Path(_get("STOREEL_DATA_DIR", "data")).expanduser().resolve(),
        # Chosen by comparing the models on the real API (October 2026): Muse Spark wrote the
        # more reliable scripts, Muse Wonder the better picture plans (see README).
        script_model=_get("STOREEL_SCRIPT_MODEL", "muse-spark-1.3"),
        script_effort=_get_choice("STOREEL_SCRIPT_EFFORT", "max", TEXT_EFFORTS),
        part_effort=_get_choice("STOREEL_PART_EFFORT", "high", TEXT_EFFORTS),
        plan_model=_get("STOREEL_PLAN_MODEL", "muse-wonder-1.0"),
        plan_effort=_get_choice("STOREEL_PLAN_EFFORT", "max", TEXT_EFFORTS),
        max_output_tokens=_get_int("STOREEL_MAX_OUTPUT_TOKENS", 32000, minimum=1000),
        check_model=_get("STOREEL_CHECK_MODEL", "muse-spark-1.3"),
        picture_check_effort=_get_choice("STOREEL_PICTURE_CHECK_EFFORT", "low", (*TEXT_EFFORTS, "off")),
        story_review_effort=_get_choice("STOREEL_STORY_REVIEW_EFFORT", "high", (*TEXT_EFFORTS, "off")),
        agent_model=_get("STOREEL_AGENT_MODEL", "muse-spark-1.3"),
        agent_effort=_get_choice("STOREEL_AGENT_EFFORT", "low", TEXT_EFFORTS),
        image_model=_get("STOREEL_IMAGE_MODEL", "muse-image-1.0"),
        image_reasoning=_get_choice("STOREEL_IMAGE_REASONING", "high", IMAGE_REASONING),
        image_parallel=_get_int("STOREEL_IMAGE_PARALLEL", 4),
        asr_model=_get("STOREEL_ASR_MODEL", "muse-voice-transcribe-1.0"),
        sam_model=_get("STOREEL_SAM_MODEL", "sam-3.1"),
        max_input_seconds=_get_int("STOREEL_MAX_INPUT_SECONDS", 180, minimum=5),
        max_upload_mb=_get_int("STOREEL_MAX_UPLOAD_MB", 1024),
        workers=_get_int("STOREEL_WORKERS", 2),
        allowed_hosts=SERVED_HOSTS + extra_hosts,
        private_projects=_get_flag("STOREEL_PRIVATE_PROJECTS"),
        showcase=_get_ids("STOREEL_SHOWCASE"),
        ttl_hours=_get_hours("STOREEL_TTL_HOURS"),
    )
