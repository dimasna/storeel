"""The project document and everything the pipeline produces for it.

A project is one reel. It is stored as one JSON document (see db.py), and media files live
next to it on disk under keys such as "work/source.mp4" (see files.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HEX_COLOR = r"^#[0-9A-Fa-f]{6}$"
DEFAULT_TITLE = "Untitled reel"
Kind = Literal["character", "object", "place"]
Display = Literal["cutaway", "overlay"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _one_line(value: str) -> str:
    return " ".join(value.split())


# ---- choices the user makes --------------------------------------------------------------


class Style(Strict):
    visual_style: Literal["cinematic", "illustration", "3d", "anime", "watercolor", "comic"] = "cinematic"
    visuals: Literal["off", "few", "balanced", "many"] = "balanced"
    captions: Literal["pill", "karaoke", "clean", "off"] = "pill"
    caption_color: str = Field("#E50914", pattern=HEX_COLOR)
    caption_position: Literal["lower", "middle"] = "lower"
    caption_case: Literal["original", "upper"] = "original"
    watermark: str = Field("", max_length=60)
    watermark_position: Literal["center", "top", "bottom"] = "center"
    language: Literal["auto", "id", "en"] = "auto"

    _clean_watermark = field_validator("watermark")(_one_line)


class Idea(Strict):
    text: str = Field(min_length=3, max_length=2000)
    format: Literal["storytime", "explainer", "tips", "review", "opinion"] = "storytime"
    tone: Literal["casual", "energetic", "calm", "funny", "dramatic"] = "casual"
    length: int = Field(30, ge=15, le=90)  # target seconds
    language: Literal["id", "en"] = "id"


class Clip(Strict):
    """An uploaded video (path A) or a recorded take (path B), as received."""

    id: str
    name: str
    key: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    hdr: bool = False
    size: int


# ---- path B: the scene script ------------------------------------------------------------


class ScriptEntity(Strict):
    id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    kind: Kind
    name: str = Field(min_length=1, max_length=80)
    description: str = Field("", max_length=800)
    real_world: bool = False


class SceneEdit(Strict):
    """A scene as the user may edit it (takes are attached by the server, never by the client)."""

    id: str = Field(pattern=r"^[a-z0-9_]{1,24}$")
    purpose: str = Field("", max_length=40)
    lines: str = Field(min_length=1, max_length=600)
    direction: str = Field("", max_length=300)
    display: Literal["none", "cutaway", "overlay"] = "none"
    visual: str = Field("", max_length=800)
    entities: list[str] = Field(default_factory=list, max_length=8)


class Scene(SceneEdit):
    take: Clip | None = None


class ScriptEdit(Strict):
    title: str = Field(min_length=1, max_length=120)
    language: Literal["id", "en"]
    scenes: list[SceneEdit] = Field(min_length=1, max_length=20)
    entities: list[ScriptEntity] = Field(default_factory=list, max_length=20)


class Script(Strict):
    title: str
    language: Literal["id", "en"]
    scenes: list[Scene]
    entities: list[ScriptEntity] = Field(default_factory=list)


# ---- what the pipeline produces ------------------------------------------------------------


class Segment(Strict):
    """Where one clip (and, on path B, its scene) sits on the reel's timeline."""

    start: float
    end: float
    clip_id: str
    scene_id: str | None = None


class Source(Strict):
    key: str  # the joined, normalised master video
    proxy_key: str  # small silent copy for Muse Spark
    audio_key: str  # 24 kHz mono WAV for Muse Voice Transcribe
    duration: float
    fps: int
    segments: list[Segment]
    digest: str


class Word(Strict):
    text: str
    start: float
    end: float


class Turn(Strict):
    id: int
    start: float
    end: float
    text: str  # what the captions show (the user may correct it)
    original: str  # what Muse Voice Transcribe heard
    speaker: str | None = None
    speech: list[tuple[float, float]] = Field(default_factory=list)  # loud stretches inside the turn
    words: list[Word] = Field(default_factory=list)


class Transcript(Strict):
    turns: list[Turn]
    duration: float
    session_id: str | None = None
    language_bias: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    digest: str = ""


class Entity(Strict):
    id: str
    kind: Kind
    name: str
    description: str
    real_world: bool = False
    visible_in_video: bool = False
    segment_prompt: str = ""
    visible_at: float | None = None
    ref_key: str | None = None  # reference image for Muse Image
    ref_source: Literal["video", "generated"] | None = None


class Region(Strict):
    """A rectangle in fractions of the frame."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


class Asset(Strict):
    key: str
    width: int
    height: int
    digest: str
    prompt: str
    references: list[str] = Field(default_factory=list)
    seconds: float = 0.0


class Moment(Strict):
    """A stretch of the reel where a generated picture is shown."""

    id: str
    start: float
    end: float
    quote: str
    display: Display
    entities: list[str] = Field(default_factory=list)
    prompt: str
    enabled: bool = True
    faces: list[Region] | None = None  # face boxes while it is on screen (None: not looked for yet)
    note: str | None = None  # e.g. why an overlay is shown full screen
    asset: Asset | None = None
    error: str | None = None
    take: int = 0  # bumped by "regenerate" so the next image is a new one


class Analysis(Strict):
    title: str
    summary: str
    language: str
    entities: list[Entity]
    moments: list[Moment]
    digest: str = ""


class Render(Strict):
    id: str
    key: str
    created_at: str
    duration: float
    size: int
    fit_mb: int | None = None


# Standard-mode list prices (https://dev.meta.ai/docs/pricing-rate-limits), for estimates only.
# Text models, per token: (input, cached input, output), matched by model id prefix.
TEXT_PRICES = {
    "muse-wonder": (4.00 / 1e6, 0.20 / 1e6, 20.00 / 1e6),
    "muse-spark": (1.25 / 1e6, 0.15 / 1e6, 4.25 / 1e6),
}
CONTRIBUTOR_PRICES = (0.10 / 1e6, 0.002 / 1e6, 0.20 / 1e6)  # the "-contributor" Muse Spark models
PRICE_IMAGE = 0.01
PRICE_SAM_IMAGE = 2.5 / 1000
PRICE_ASR_SECOND = 0.18 / 3600


def text_model_name(model: str) -> str:
    """How the text model is called in logs and the studio, e.g. "Muse Wonder"."""
    return "Muse Wonder" if model.startswith("muse-wonder") else "Muse Spark"


def text_usd(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    """The list price of one text-model call; unknown models are priced like Muse Wonder."""
    if model.endswith("-contributor"):
        price_in, price_cached, price_out = CONTRIBUTOR_PRICES
    else:
        prefix = next((p for p in TEXT_PRICES if model.startswith(p)), "muse-wonder")
        price_in, price_cached, price_out = TEXT_PRICES[prefix]
    uncached = max(0, input_tokens - cached_tokens)
    return uncached * price_in + cached_tokens * price_cached + output_tokens * price_out


class Usage(Strict):
    # Token counts of the text model (Muse Spark or Muse Wonder); the names predate Wonder.
    spark_input_tokens: int = 0
    spark_cached_tokens: int = 0
    spark_output_tokens: int = 0
    text_usd: float = 0.0  # those tokens priced by the model that used them
    images: int = 0
    sam_images: int = 0
    asr_seconds: float = 0.0

    def add(self, other: Usage) -> None:
        for name in type(self).model_fields:
            setattr(self, name, getattr(self, name) + getattr(other, name))

    @property
    def estimated_usd(self) -> float:
        """Not stored (the stored document must round-trip): derived from the counters."""
        text = self.text_usd
        if not text and (self.spark_input_tokens or self.spark_output_tokens):
            # Projects from before text_usd was counted only ever used Muse Spark.
            text = text_usd(
                "muse-spark", self.spark_input_tokens, self.spark_cached_tokens, self.spark_output_tokens
            )
        return round(
            text
            + self.images * PRICE_IMAGE
            + self.sam_images * PRICE_SAM_IMAGE
            + self.asr_seconds * PRICE_ASR_SECOND,
            4,
        )


class Project(Strict):
    id: str
    title: str = Field(max_length=120)
    path: Literal["video", "idea"]
    created_at: str
    updated_at: str
    style: Style = Field(default_factory=Style)
    clips: list[Clip] = Field(default_factory=list)  # path A, in reel order
    idea: Idea | None = None  # path B
    script: Script | None = None  # path B
    source: Source | None = None
    transcript: Transcript | None = None
    analysis: Analysis | None = None
    renders: list[Render] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    error: str | None = None  # why the last job failed

    def inputs(self) -> list[Clip]:
        """The clips that make up the reel, in order."""
        if self.path == "idea":
            return [scene.take for scene in (self.script.scenes if self.script else []) if scene.take]
        return list(self.clips)

    def invalidate_media(self) -> None:
        """The inputs changed: everything derived from them has to be made again."""
        self.source = None
        self.transcript = None
        self.analysis = None
