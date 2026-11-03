// Human labels for the backend's enum values (ported from the previous UI). The UI reads the
// available enum values from the config schema and looks their label up here.

export const LABELS: Record<string, Record<string, string>> = {
  visual_style: {
    realistic_3d: "Realistic 3D render",
    cinematic: "Cinematic photo",
    illustration: "Illustration",
    "3d": "3D animation",
    anime: "Anime",
    watercolor: "Watercolour",
    comic: "Comic",
  },
  visuals: { off: "No pictures", few: "A few", balanced: "Balanced", many: "Many" },
  captions: {
    pill: "Highlight pill",
    karaoke: "Coloured word",
    clean: "Plain",
    bold: "Bold, word by word",
    serif: "Serif, word by word",
    off: "No captions",
  },
  caption_position: { lower: "Lower third", middle: "Middle" },
  caption_case: { original: "As spoken", upper: "UPPERCASE" },
  title_style: { behind: "Behind the speaker", front: "In front of the speaker", off: "No title" },
  motion: { animated: "Animated (HyperFrames)", plain: "Plain fades" },
  background: {
    dalang: "Dalang: your own video",
    scene: "Scene: cut out, the pictures behind you",
    studio: "Studio: cut out, a studio backdrop",
  },
  theme: {
    auto: "Auto",
    none: "None: the plain look",
    romance: "Romance (senja)",
    horror: "Horror",
    mystery: "Mystery (noir)",
    drama: "Drama (sinetron)",
    legend: "Legend (wayang)",
  },
  genre: {
    auto: "Auto: Muse Spark picks it",
    romance: "Romance",
    horror: "Horror",
    mystery: "Mystery",
    drama: "Drama",
    legend: "Legend",
    other: "Other (no theme)",
  },
  watermark_position: { center: "Centre", top: "Top", bottom: "Bottom" },
  language: { auto: "Detect", id: "Indonesian (+ English)", en: "English" },
  format: { storytime: "Storytime", explainer: "Explainer", tips: "Tips", review: "Review", opinion: "Opinion" },
  tone: { casual: "Casual", energetic: "Energetic", calm: "Calm", funny: "Funny", dramatic: "Dramatic" },
  idea_language: { id: "Indonesian", en: "English" },
  picture_layout: { cards: "Cards and cut-outs over the speaker", full: "Full screen" },
  speaker_behind: {
    blur: "Blur the speaker",
    sharp: "Keep the speaker sharp",
    auto: "Blur only when the face is covered",
    top: "Blur only behind a picture at the top",
  },
  display: { none: "Speaker only", overlay: "Card", cutout: "Cut-out", cutaway: "Full screen" },
  novel_language: { id: "Indonesian", en: "English" },
  narration: {
    casual: "Casual, like telling a friend",
    warm: "Warm and gentle",
    dramatic: "Dramatic narrator",
    funny: "Funny gossip",
  },
  act: {
    hook: "Hook",
    bridge: "Bridge",
    setup: "Setup",
    rise: "Rise",
    turn: "Turn",
    cliffhanger: "Cliffhanger",
    outro: "Outro",
  },
};

export const JOB_NAMES: Record<string, string> = {
  script: "Writing the script",
  story: "Writing the part",
  process: "Processing",
  regenerate: "Regenerating a picture",
  render: "Rendering the reel",
  agent: "Editor",
  agent_apply: "Running the approved changes",
};

export const STAGES: Record<string, [string, string][]> = {
  video: [
    ["upload", "Upload"],
    ["ready", "Style"],
    ["processing", "Process"],
    ["review", "Review"],
    ["done", "Render"],
  ],
  idea: [
    ["idea", "Idea"],
    ["record", "Script & record"],
    ["ready", "Style"],
    ["processing", "Process"],
    ["review", "Review"],
    ["done", "Render"],
  ],
  novel: [
    ["story", "Part script"],
    ["record", "Record"],
    ["ready", "Style"],
    ["processing", "Process"],
    ["review", "Review"],
    ["done", "Render"],
  ],
};

export function labelFor(field: string, value: string): string {
  return LABELS[field]?.[value] ?? value;
}

export function enumOf(schema: { properties?: Record<string, { enum?: string[] }> } | undefined, field: string): string[] {
  return schema?.properties?.[field]?.enum ?? [];
}
