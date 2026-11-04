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
# How a picture is shown. The stored names predate the labels: "overlay" is a picture card in
# the upper part of the frame, "cutout" is the subject alone with its background removed (SAM),
# "cutaway" fills the screen.
Display = Literal["overlay", "cutout", "cutaway"]
# A reel's genre theme (see pipeline/themes.py), one per novel Genre (below) but "other": "auto"
# follows a novel part's genre (no theme for other reels), "none" keeps the plain look.
Theme = Literal["auto", "none", "romance", "horror", "mystery", "drama", "legend"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _one_line(value: str) -> str:
    return " ".join(value.split())


# ---- choices the user makes --------------------------------------------------------------


class Style(Strict):
    visual_style: Literal[
        "realistic_3d", "cinematic", "illustration", "3d", "anime", "watercolor", "comic"
    ] = "cinematic"
    visuals: Literal["off", "few", "balanced", "many"] = "balanced"
    # "cards": pictures float over the speaker as cards and cut-outs; "full": they fill the screen.
    picture_layout: Literal["cards", "full"] = "cards"
    # What the speaker looks like behind a card or cut-out: "auto" blurs only when it covers the face,
    # "top" only behind a picture in the upper part (characters standing at the bottom keep it sharp).
    speaker_behind: Literal["blur", "sharp", "auto", "top"] = "blur"
    # "bold" and "serif" bring each word in as it is said and set the stressed words (picked by
    # Muse Spark) in an italic serif, in caption_color; the others highlight the spoken word.
    captions: Literal["pill", "karaoke", "clean", "bold", "serif", "off"] = "pill"
    caption_color: str = Field("#E50914", pattern=HEX_COLOR)
    caption_position: Literal["lower", "middle"] = "lower"
    caption_case: Literal["original", "upper"] = "original"
    watermark: str = Field("", max_length=60)
    watermark_position: Literal["center", "top", "bottom"] = "center"
    language: Literal["auto", "id", "en"] = "auto"
    # A big title over the first seconds: "behind" the speaker (SAM 3.1 tracks them, so their head
    # and shoulders cover the words), "front" of them, or "off". title_text "" is the reel's title.
    title_style: Literal["behind", "front", "off"] = "behind"
    title_text: str = Field("", max_length=40)
    # "animated": HyperFrames brings in the title's letters, the photo cards (a 3D swing) and a
    # part's end screen; "plain": they fade in.
    motion: Literal["animated", "plain"] = "animated"
    # The reel's look, by what is behind the speaker: "dalang" (their own video, as a storyteller
    # with the characters standing at the bottom and the pictures up top), or cut out of every
    # frame by SAM 3.1: "scene" (each picture fills the screen behind them; their own video in
    # between) or "studio" (a moving glow in caption_color, the pictures as cards, an outline).
    background: Literal["dalang", "scene", "studio"] = "dalang"
    # A genre theme over the look (free, never a cost choice): the colour grade of the speaker's
    # video, the caption style and highlight (only while those are "pill" and the default red),
    # the photo cards' frame, the title, the studio backdrop, an effect on the stressed words and
    # one touch of its own. See pipeline/themes.py.
    theme: Theme = "auto"
    # Where the cut-out speaker stands in the scene and studio looks: their video scaled about its
    # bottom middle (1 = as recorded), that middle across the frame (0 the left edge, 1 the right
    # edge), and the video's bottom edge down the frame (1 the frame's bottom; less lifts them,
    # more sinks them, which keeps the head in view when they are bigger).
    speaker_scale: float = Field(1.0, ge=0.3, le=1.6)
    speaker_x: float = Field(0.5, ge=0.0, le=1.0)
    speaker_y: float = Field(1.0, ge=0.6, le=1.8)
    # While a picture up top is showing (a card, a cut-out object, a note, chat bubbles, the poll),
    # the speaker steps back, smaller about the bottom middle of their video, so it never covers
    # them, in every look ("auto"); "off" keeps them where they are, behind it (speaker_behind).
    speaker_room: Literal["auto", "off"] = "auto"
    # Free effects drawn at render time (see pipeline/effects.py): the voiced character moving
    # with the voice, living stills, characters sliding in, a rim of light round the stepped-back
    # speaker, a spotlight at the cliffhanger and the theme's particles; "off" leaves them out.
    effects: Literal["on", "off"] = "on"
    # Two of the effects on their own, while effects is "on": the punch-in on the face (at the
    # hook's end and the cliffhanger), and the theme's particles.
    punch_in: Literal["on", "off"] = "on"
    particles: Literal["on", "off"] = "on"

    _clean_watermark = field_validator("watermark")(_one_line)
    _clean_title = field_validator("title_text")(_one_line)

    @field_validator("speaker_behind", mode="before")
    @classmethod
    def _top_was_card(cls, value: object) -> object:
        return "top" if value == "card" else value  # its name for a day, when it was cards only

    @field_validator("background", mode="before")
    @classmethod
    def _dalang_was_original(cls, value: object) -> object:
        return "dalang" if value == "original" else value  # its name before the look had one


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
    display: Literal["none", "overlay", "cutout", "cutaway"] = "none"
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


# ---- path C: novels ---------------------------------------------------------------------------
#
# A novel is told as a series, one reel per chapter (a "part").
# Each part is a teaser: the hook on camera, the story in beats over pictures, a poll and a
# call to action. The narrator is the user, recording the part take by take. A character bible
# grows chapter by chapter, so every part shows the same people; chapter N sees only what the
# chapters before it added, so writing a chapter again redesigns only its own additions.

Narration = Literal["casual", "warm", "dramatic", "funny"]
# What a novel's parts are themed by (see Theme above): "auto" until Muse Spark picks one of the
# others from the synopsis and the chapter, as the first part is written; "other" has no theme.
Genre = Literal["auto", "romance", "horror", "mystery", "drama", "legend", "other"]
VisualStyle = Literal["realistic_3d", "cinematic", "illustration", "3d", "anime", "watercolor", "comic"]
Act = Literal["hook", "bridge", "setup", "rise", "turn", "cliffhanger", "outro"]


class BibleNote(Strict):
    chapter: int
    note: str


class BibleLook(Strict):
    """What a character wears in one chapter, and their portrait in it (a novel file key)."""

    chapter: int
    outfit: str
    image: str | None = None


class BibleCharacter(Strict):
    id: str
    name: str
    label: str  # what viewers call them on screen, lowercase
    role: str = ""
    description: str  # who they are (age, build, face, hair), never their clothes
    subject: str = "person"  # what SAM cuts out of their portrait: "woman", "old man", "cat"
    slot: Literal["left", "right"] = "left"
    created_in: int
    notes: list[BibleNote] = Field(default_factory=list)
    looks: list[BibleLook] = Field(default_factory=list)


class BibleProp(Strict):
    """An object that recurs across chapters, drawn once."""

    id: str
    description: str
    subject: str = ""
    shape: Literal["wide", "tall", "square"] = "square"
    created_in: int
    image: str | None = None


class Bible(Strict):
    characters: dict[str, BibleCharacter] = Field(default_factory=dict)
    props: dict[str, BibleProp] = Field(default_factory=dict)

    def before(self, chapter: int) -> Bible:
        """What the chapters before `chapter` designed: the bible that chapter is written with."""
        characters = {}
        for cid, c in self.characters.items():
            if c.created_in < chapter:
                characters[cid] = c.model_copy(
                    update={
                        "notes": [n for n in c.notes if n.chapter < chapter],
                        "looks": [x for x in c.looks if x.chapter < chapter],
                    }
                )
        props = {pid: p for pid, p in self.props.items() if p.created_in < chapter}
        return Bible(characters=characters, props=props)


class Chapter(Strict):
    number: int = Field(ge=1, le=999)
    title: str = Field("", max_length=160)
    text: str = Field(min_length=200, max_length=200_000)
    created_at: str
    project_id: str | None = None  # its reel, once opened


class Novel(Strict):
    id: str
    title: str = Field(min_length=1, max_length=120)
    synopsis: str = Field("", max_length=4000)
    language: Literal["id", "en"] = "id"
    narration: Narration = "casual"
    visual_style: VisualStyle = "realistic_3d"  # a novel's characters as realistic 3D renders
    watermark: str = Field("", max_length=60)
    genre: Genre = "auto"  # its parts' theme, on the theme "auto"
    created_at: str
    updated_at: str
    chapters: list[Chapter] = Field(default_factory=list)
    bible: Bible = Field(default_factory=Bible)
    owner: str | None = None  # the browser that made it (a hash of its cookie); None: made before owners

    _clean_watermark = field_validator("watermark")(_one_line)

    def chapter(self, number: int) -> Chapter | None:
        return next((c for c in self.chapters if c.number == number), None)


class StoryNote(Strict):
    """Writing the viewer must read (an image model cannot write): drawn as text."""

    text: str = ""
    style: Literal["paper", "sign", "screen"] = "paper"


class ChatMessage(Strict):
    sender: str
    text: str


class StoryShow(Strict):
    """What the screen shows while a beat is spoken: up to two characters standing at the bottom,
    at most one of prop / photo / chat / note, and an optional red tag."""

    characters: list[str] = Field(default_factory=list)
    prop: str = ""
    photo: str = ""
    chat: list[ChatMessage] = Field(default_factory=list)
    note: StoryNote = Field(default_factory=StoryNote)
    tag: str = ""


class StorySwitch(Strict):
    at: str  # words of the beat where the picture changes
    show: StoryShow


class Beat(Strict):
    act: Act
    text: str  # spoken
    speaker: str = "narrator"  # or the id of the character being quoted
    see: str = ""  # English: who and what the viewer should see
    direction: str = ""  # a delivery note for the narrator
    show: StoryShow = Field(default_factory=StoryShow)
    switch: StorySwitch | None = None
    take: str = ""  # the scene (take) this beat is recorded in
    # The creator chose what this beat shows and when (in the editor's chat): its screens stay
    # even when they are shorter than the compositor would otherwise allow.
    pinned: bool = False


class StoryCharacter(Strict):
    id: str
    name: str
    label: str
    role: str = ""
    description: str
    outfit: str
    subject: str = "person"
    slot: Literal["left", "right"] = "left"


class StoryLook(Strict):
    id: str
    outfit: str


class StoryVariant(Strict):
    id: str
    base: str
    change: str
    persistent: bool = False


class StoryProp(Strict):
    id: str
    description: str
    subject: str = ""
    shape: Literal["wide", "tall", "square"] = "square"
    size: Literal["small", "medium", "large"] = "medium"
    refs: list[str] = Field(default_factory=list)
    people: int = 0
    framing: Literal["full", "close-up"] = "full"
    backdrop: bool = False
    recurring: bool = False


class StoryPhoto(Strict):
    id: str
    description: str
    title: str = ""


class StoryBibleNote(Strict):
    id: str
    note: str


class Poll(Strict):
    text: str
    a: str
    b: str


class Story(Strict):
    """One part's script, for the user to record."""

    part: int
    continuing: bool  # an earlier part exists: the hook continues, beat 1 bridges from it
    chapter_title: str
    hook: str
    hook_direction: str = ""
    beats: list[Beat]
    poll: Poll
    cta: str
    characters: list[StoryCharacter] = Field(default_factory=list)
    looks: list[StoryLook] = Field(default_factory=list)
    variants: list[StoryVariant] = Field(default_factory=list)
    props: list[StoryProp] = Field(default_factory=list)
    photos: list[StoryPhoto] = Field(default_factory=list)
    bible_notes: list[StoryBibleNote] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)  # what the checks still found
    review_found: int = 0  # the pictures the storyboard review found not matching (then fixed)
    # Made from the user's own video of the part: its words are what they said (the video is the
    # recording), and the poll and the call to action are there only if they said them.
    from_video: bool = False


class PartPicture(Strict):
    """A picture a novel part shows: a character standing (from the bible), an object or a scene
    cut out, or a card (a photo, a place). `scope` says whose files hold it."""

    id: str
    kind: Literal["character", "variant", "prop", "photo"]
    display: Literal["standing", "object", "scene", "card"]
    scope: Literal["novel", "project"]
    key: str | None = None
    cutout: bool = False
    width: int = 0
    height: int = 0
    prompt: str = ""
    error: str | None = None
    checked: bool = False  # a character portrait the checker looked at
    problems: list[str] = Field(default_factory=list)  # what it still found wrong (after a redraw)


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
    emphasis: bool = False  # a word the captions stress (picked by Muse Spark)


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
    emphasis_picked: bool = False  # Muse Spark chose the words to stress (none may be stressed)


class SpeakerMasks(Strict):
    """Where the speaker is, frame by frame, while the title is up: SAM 3.1 video masks of the
    person, stored as one compressed array (frames x height x width, at half the reel's width
    and height)."""

    key: str
    start: float  # seconds on the reel's timeline of the first mask
    fps: float
    frames: int
    width: int
    height: int
    digest: str  # the source video and the window they were made for


class SpeakerTrack(Strict):
    """Where the speaker is in every frame of the reel, for the cut-out backgrounds: SAM 3.1
    video masks at `fps` from the start, packed bits (frames x bytes) at `width` x `height`.
    An empty key: SAM found no speaker, remembered so it is not asked again."""

    key: str
    fps: float
    frames: int
    width: int
    height: int
    digest: str
    # where they usually are, as recorded (x0, y0, x1, y1 in fractions of the frame): the box of
    # the pixels they cover on most frames; None for a track made before it was kept
    box: tuple[float, float, float, float] | None = None


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
    cutout: bool = False  # an RGBA picture of the subject alone, cut out by SAM


class Moment(Strict):
    """A stretch of the reel where a generated picture is shown."""

    id: str
    start: float
    end: float
    quote: str
    display: Display
    planned: Display | None = None  # what the planner chose; `display` follows the layout setting
    chosen: bool = False  # the user picked `display` in Review: the layout setting leaves it alone
    entities: list[str] = Field(default_factory=list)
    prompt: str
    subject: str = ""  # the noun phrase SAM looks for when it is a cut-out, e.g. "orange cat"
    enabled: bool = True
    faces: list[Region] | None = None  # face boxes while it is on screen (None: not looked for yet)
    note: str | None = None  # e.g. why a cut-out is shown as a card
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

    def apply_layout(self, layout: str) -> list[str]:
        """Set each picture's display from the layout setting (unless the user chose one).
        Returns the ids of the moments whose display changed."""
        changed = []
        for moment in self.moments:
            if moment.chosen:
                continue
            # Plans from before cut-outs existed only knew "cutaway" (full screen) and "overlay".
            planned = moment.planned or ("overlay" if moment.display == "cutaway" else moment.display)
            moment.planned = planned
            wanted = "cutaway" if layout == "full" else planned
            if moment.display != wanted:
                moment.display = wanted
                changed.append(moment.id)
        return changed


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
PRICE_SAM_FRAME = 0.20 / 1000  # video segmentation, billed for at least SAM_MIN_FRAMES a request
SAM_MIN_FRAMES = 50
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
    sam_frames: int = 0  # video frames SAM segmented (as billed)
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
            + self.sam_frames * PRICE_SAM_FRAME
            + self.asr_seconds * PRICE_ASR_SECOND,
            4,
        )


# ---- the editing agent ----------------------------------------------------------------------


class AgentAction(Strict):
    """One change the editing agent made, or one it proposes and the user has to approve.

    Free edits (a caption, showing or hiding pictures, the style) are applied at once and
    stored as "done". A new picture or a render costs money or time, so it is stored as
    "pending" and runs only once the user approves it.
    """

    id: str
    kind: Literal["caption", "pictures", "style", "picture", "outfit", "render", "screen", "undo"]
    summary: str  # what the chat shows, e.g. 'Caption at 0:12: "..."'
    status: Literal["done", "pending", "approved", "dismissed", "failed"] = "done"
    moment_id: str | None = None  # "picture": the moment to draw again
    display: Display | None = None  # "picture": its new shape
    prompt: str | None = None  # "picture": its new prompt
    character: str | None = None  # "outfit": the novel character, by id
    outfit: str | None = None  # "outfit": what they wear in this part from now on
    fit_mb: int | None = None  # "render": keep the file under this size
    cost_usd: float = 0.0  # an estimate at list prices
    error: str | None = None


class AgentMessage(Strict):
    role: Literal["user", "assistant"]
    text: str
    created_at: str
    actions: list[AgentAction] = Field(default_factory=list)


class MomentWas(Strict):
    """A picture's visibility and times before an edit."""

    id: str
    enabled: bool
    start: float
    end: float


class BeatWas(Strict):
    """A novel part's beat screens before an edit, by the beat's index."""

    index: int
    show: StoryShow
    switch: StorySwitch | None = None
    pinned: bool = False


class EditUndo(Strict):
    """What one request to the editor changed, as it was before, so "undo" can put it back.
    Only the free edits: a new picture, an outfit or a render is not undone."""

    summary: str  # what the request changed, for the chat
    style: dict[str, str | float] = Field(default_factory=dict)  # changed settings: old values
    transcript_digest: str = ""  # the captions below belong to this transcription
    turns: list[Turn] = Field(default_factory=list)  # the captions it changed, as they were
    emphasis_picked: bool | None = None
    moments: list[MomentWas] = Field(default_factory=list)
    beats: list[BeatWas] = Field(default_factory=list)
    poll: Poll | None = None
    cta: str | None = None


class AgentChat(Strict):
    messages: list[AgentMessage] = Field(default_factory=list)
    undo: list[EditUndo] = Field(default_factory=list)  # the latest last

    def latest_actions(self, status: str) -> list[AgentAction]:
        """The actions with `status` in the agent's latest reply (older replies are history)."""
        reply = next((m for m in reversed(self.messages) if m.role == "assistant"), None)
        return [a for a in reply.actions if a.status == status] if reply else []

    def dismiss_pending(self) -> None:
        for message in self.messages:
            for action in message.actions:
                if action.status == "pending":
                    action.status = "dismissed"


class Project(Strict):
    id: str
    title: str = Field(max_length=120)
    path: Literal["video", "idea", "novel"]
    created_at: str
    updated_at: str
    style: Style = Field(default_factory=Style)
    clips: list[Clip] = Field(default_factory=list)  # path A, in reel order
    idea: Idea | None = None  # path B
    script: Script | None = None  # paths B and C: the scenes (takes) to record
    novel_id: str | None = None  # path C: the novel and chapter this reel tells
    chapter: int | None = None
    brief: str = Field("", max_length=600)  # path C: what the creator asked the part's writer for
    story: Story | None = None  # path C: the part's script
    part_pictures: dict[str, PartPicture] | None = None  # path C: what the part shows, by id
    part_faces: dict[str, list[Region]] = Field(default_factory=dict)  # path C: face boxes per take
    speaker_masks: SpeakerMasks | None = None  # the speaker while the title is up (SAM 3.1 video)
    speaker_track: SpeakerTrack | None = None  # the speaker all through, for a cut-out background
    source: Source | None = None
    transcript: Transcript | None = None
    analysis: Analysis | None = None
    renders: list[Render] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    error: str | None = None  # why the last job failed
    agent: AgentChat = Field(default_factory=AgentChat)  # the editing agent's conversation
    owner: str | None = None  # the browser that made it (a hash of its cookie); None: made before owners

    def inputs(self) -> list[Clip]:
        """The clips that make up the reel, in order."""
        if self.path == "novel" and self.clips:  # one video of the whole part, instead of takes
            return list(self.clips)
        if self.path in ("idea", "novel"):
            return [scene.take for scene in (self.script.scenes if self.script else []) if scene.take]
        return list(self.clips)

    def invalidate_media(self) -> None:
        """The inputs changed: everything derived from them has to be made again."""
        self.source = None
        self.transcript = None
        self.analysis = None
        self.part_faces = {}
        self.agent.dismiss_pending()  # its proposals name captions and pictures that are gone
