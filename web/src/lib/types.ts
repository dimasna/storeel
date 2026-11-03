// The JSON shapes the backend exchanges (see src/storeel/models.py and projects.py).
// Kept loose where the backend sends schema-driven enums the UI reads dynamically.

export type Path = "video" | "idea" | "novel";
export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";
export type Display = "overlay" | "cutout" | "cutaway";

export interface Job {
  id: string;
  kind: string;
  status: JobStatus;
  step: string;
  progress: number;
  error: string | null;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  log: string;
}

export interface Style {
  visual_style: string;
  visuals: string;
  picture_layout: string;
  speaker_behind: string;
  captions: string;
  caption_color: string;
  caption_position: string;
  caption_case: string;
  watermark: string;
  watermark_position: string;
  language: string;
  title_style: string;
  title_text: string;
}

export interface Idea {
  text: string;
  format: string;
  tone: string;
  length: number;
  language: string;
}

export interface Clip {
  id: string;
  name: string;
  key: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  has_audio: boolean;
  hdr: boolean;
  size: number;
}

export interface SceneEntity {
  id: string;
  kind: string;
  name: string;
  description: string;
  real_world: boolean;
}

export interface Scene {
  id: string;
  purpose: string;
  lines: string;
  direction: string;
  display: string;
  visual: string;
  entities: string[];
  take: Clip | null;
}

export interface Script {
  title: string;
  language: string;
  scenes: Scene[];
  entities: SceneEntity[];
}

export interface Word {
  text: string;
  start: number;
  end: number;
}

export interface Turn {
  id: number;
  start: number;
  end: number;
  text: string;
  original: string;
  speaker: string | null;
  speech: [number, number][];
  words: Word[];
}

export interface Transcript {
  turns: Turn[];
  duration: number;
}

export interface Asset {
  key: string;
  width: number;
  height: number;
  prompt: string;
  cutout: boolean;
}

export interface Moment {
  id: string;
  start: number;
  end: number;
  quote: string;
  display: Display;
  enabled: boolean;
  prompt: string;
  note: string | null;
  asset: Asset | null;
  error: string | null;
}

export interface Entity {
  id: string;
  kind: string;
  name: string;
  description: string;
  ref_key: string | null;
  ref_source: "video" | "generated" | null;
}

export interface Analysis {
  title: string;
  summary: string;
  entities: Entity[];
  moments: Moment[];
}

export interface Render {
  id: string;
  key: string;
  created_at: string;
  duration: number;
  size: number;
  fit_mb: number | null;
}

export interface Usage {
  spark_input_tokens: number;
  spark_output_tokens: number;
  images: number;
  sam_images: number;
  sam_frames: number;
  asr_seconds: number;
  estimated_usd: number;
}

export interface Beat {
  act: string;
  text: string;
  speaker: string;
  direction: string;
  take: string;
  show?: ShowTags;
  switch?: { at: string; show: ShowTags } | null;
}

export interface ShowTags {
  characters?: string[];
  prop?: string;
  photo?: string;
  chat?: { sender: string; text: string }[];
  note?: { text: string } | null;
  tag?: string;
}

export interface Story {
  part: number;
  continuing: boolean;
  chapter_title: string;
  hook: string;
  hook_direction: string;
  beats: Beat[];
  poll: { text: string; a: string; b: string };
  cta: string;
  from_video: boolean;
  problems: string[];
  /** The pictures the storyboard review found not matching the chapter, then fixed. */
  review_found?: number;
  characters?: { id: string; name: string; label: string; role: string; description: string; outfit: string }[];
  looks?: { id: string; outfit: string }[];
  variants?: { id: string; base: string; change: string; persistent: boolean }[];
  props?: { id: string; description: string; recurring: boolean }[];
  photos?: { id: string; title: string; description: string }[];
  bible_notes?: { id: string; note: string }[];
}

export interface PartPicture {
  id: string;
  kind: string;
  display: string;
  scope: "novel" | "project";
  key: string | null;
  cutout: boolean;
  prompt: string;
  error: string | null;
  checked: boolean;
  problems: string[];
}

/** What a part's first pass costs at list prices, before it runs (rendering is free). */
export interface PartEstimate {
  write_usd: number;
  draw_usd: number;
  transcribe_usd: number;
  total_usd: number;
  pictures: number;
  seconds: number;
}

export interface NovelPart {
  id: string;
  title: string;
  language: string;
  narration: string;
  visual_style: string;
  chapter_title: string;
  chapter_text: string;
  opening: string;
  estimate: PartEstimate;
}

export interface HeardNote {
  status: "ok" | "partly heard" | "not heard";
  share: number;
}

export interface CaptionNote {
  script: string | null;
  differs: string[];
}

export type AgentActionStatus = "done" | "pending" | "approved" | "dismissed" | "failed";

export interface AgentAction {
  id: string;
  kind: "caption" | "pictures" | "style" | "picture" | "outfit" | "render" | "screen";
  summary: string;
  status: AgentActionStatus;
  moment_id: string | null;
  display: Display | null;
  prompt: string | null;
  character: string | null;
  outfit: string | null;
  fit_mb: number | null;
  cost_usd: number;
  error: string | null;
}

export interface AgentMessage {
  role: "user" | "assistant";
  text: string;
  created_at: string;
  actions: AgentAction[];
}

export interface Project {
  id: string;
  title: string;
  path: Path;
  created_at: string;
  updated_at: string;
  style: Style;
  clips: Clip[];
  idea: Idea | null;
  script: Script | null;
  novel_id: string | null;
  chapter: number | null;
  brief: string;
  story: Story | null;
  part_pictures: Record<string, PartPicture> | null;
  source: unknown | null;
  transcript: Transcript | null;
  analysis: Analysis | null;
  renders: Render[];
  usage: Usage;
  error: string | null;
  agent: { messages: AgentMessage[] };
  read_only: boolean;
  stage: string;
  job: Job | null;
  input_seconds: number;
  heard: Record<string, HeardNote>;
  caption_notes: Record<string, CaptionNote>;
  novel: NovelPart | null;
  /** A novel part's timeline: what the reel shows when (empty until it is processed). */
  screens?: PartScreen[];
}

export interface PartScreen {
  kind: "hook" | "beat" | "poll" | "cta";
  start: number;
  end: number;
  beat?: number;
  characters?: string[];
  prop?: string;
  photo?: string;
  tag?: string;
}

export interface ProjectSummary {
  id: string;
  title: string;
  path: Path;
  stage: string;
  updated_at: string;
  input_seconds: number;
  renders: number;
  cover: string | null;
  read_only: boolean;
}

export interface BibleCharacter {
  id: string;
  name: string;
  label: string;
  role: string;
  description: string;
  created_in: number;
  notes: { chapter: number; note: string }[];
  looks: { chapter: number; outfit: string; image: string | null }[];
}

export interface BibleProp {
  id: string;
  description: string;
  created_in: number;
  image: string | null;
}

export interface Chapter {
  number: number;
  title: string;
  chars: number;
  project_id: string | null;
  stage: string | null;
  renders: number;
}

export interface Novel {
  id: string;
  title: string;
  synopsis: string;
  language: string;
  narration: string;
  visual_style: string;
  watermark: string;
  created_at: string;
  updated_at: string;
  bible: { characters: Record<string, BibleCharacter>; props: Record<string, BibleProp> };
  chapters: Chapter[];
  next_chapter: number;
  read_only: boolean;
}

export interface NovelSummary {
  id: string;
  title: string;
  language: string;
  chapters: number;
  characters: number;
  updated_at: string;
  read_only: boolean;
}

export interface JsonSchema {
  properties?: Record<string, { enum?: string[]; default?: unknown }>;
}

export interface Config {
  bring_your_own_key: boolean;
  max_input_seconds: number;
  max_upload_mb: number;
  /** Hours a reel is kept after it was last touched; 0 keeps everything (a local studio). */
  ttl_hours?: number;
  models: {
    script: string;
    script_name: string;
    plan: string;
    plan_name: string;
    image: string;
    asr: string;
    sam: string;
  };
  style: JsonSchema;
  idea: JsonSchema;
  novel: JsonSchema;
  narration: Record<string, Record<string, { opening: string; voice: string }>>;
}
