import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronUp,
  Download,
  FileText,
  Film,
  Images,
  Loader2,
  MessageSquarePlus,
  Pause,
  Play,
  RefreshCw,
  Sparkles,
  Volume2,
  VolumeX,
} from "lucide-react";
import { mediaUrl, novelMediaUrl } from "@/lib/api";
import type { PartEstimate, PartPicture, PartScreen, Project, Scene } from "@/lib/types";
import { jobActive } from "@/lib/use-project";
import { labelFor } from "@/lib/labels";
import { seconds } from "@/lib/format";
import { useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";

// The part studio's editor panel, after OpusClip's: a toolbar (the view, then Render again and
// Download), the stage (the reel, the script or the pictures), a player bar, and a timeline of
// what the reel shows when. The timeline is read-only: changes go through the chat, and a
// moment can be handed to it from here.

export type EditorView = "reel" | "script" | "pictures";

const VIEWS: [EditorView, string, typeof Film][] = [
  ["reel", "Reel", Film],
  ["script", "Script", FileText],
  ["pictures", "Pictures", Images],
];

export function timeLabel(value: number): string {
  const total = Math.max(0, Math.floor(value));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function pictureUrl(project: Project, picture: PartPicture | undefined): string | null {
  if (!picture?.key) return null;
  return picture.scope === "novel" && project.novel
    ? novelMediaUrl(project.novel.id, picture.key)
    : mediaUrl(project.id, picture.key);
}

function ToolButton({
  label,
  active,
  onClick,
  children,
  disabled,
}: {
  label: string;
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "grid size-10 place-items-center rounded-xl transition-colors disabled:opacity-35",
        active ? "text-accent" : "text-muted-foreground hover:bg-card hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

/** The reel's video, and the state the player bar and the timeline share. */
function usePlayer(src: string | null) {
  const video = useRef<HTMLVideoElement>(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);

  useEffect(() => {
    setTime(0);
    setPlaying(false);
  }, [src]);

  useEffect(() => {
    const el = video.current;
    if (!el) return;
    let frame = 0;
    const tick = () => {
      setTime(el.currentTime);
      frame = requestAnimationFrame(tick);
    };
    const onPlay = () => {
      setPlaying(true);
      frame = requestAnimationFrame(tick);
    };
    const onPause = () => {
      setPlaying(false);
      cancelAnimationFrame(frame);
      setTime(el.currentTime);
    };
    const onMeta = () => setDuration(el.duration || 0);
    const onSeeked = () => setTime(el.currentTime);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    el.addEventListener("ended", onPause);
    el.addEventListener("loadedmetadata", onMeta);
    el.addEventListener("seeked", onSeeked);
    if (el.readyState >= 1) onMeta();
    return () => {
      cancelAnimationFrame(frame);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
      el.removeEventListener("ended", onPause);
      el.removeEventListener("loadedmetadata", onMeta);
      el.removeEventListener("seeked", onSeeked);
    };
  }, [src]);

  const seek = useCallback((t: number) => {
    const el = video.current;
    setTime(t);
    if (el && Number.isFinite(t)) el.currentTime = Math.max(0, Math.min(t, el.duration || t));
  }, []);
  const toggle = useCallback(() => {
    const el = video.current;
    if (!el) return;
    if (el.paused) el.play().catch(() => {});
    else el.pause();
  }, []);
  const toggleMute = useCallback(() => {
    const el = video.current;
    if (!el) return;
    el.muted = !el.muted;
    setMuted(el.muted);
  }, []);
  return { video, time, duration, playing, muted, seek, toggle, toggleMute };
}

export function PartEditor({
  project,
  view,
  onView,
  estimate,
  busy,
  onRender,
  onAsk,
  className,
  script,
}: {
  project: Project;
  view: EditorView;
  onView: (view: EditorView) => void;
  estimate: PartEstimate;
  busy: boolean;
  onRender: () => void;
  onAsk: (text: string) => void;
  className?: string;
  script: ReactNode;
}) {
  const last = project.renders[project.renders.length - 1];
  const src = last ? mediaUrl(project.id, last.key) : null;
  const player = usePlayer(src);
  const active = jobActive(project);
  const job = project.job;
  const screens = project.screens ?? [];
  const length = player.duration || last?.duration || project.transcript?.duration || screens.at(-1)?.end || 0;
  const [timelineOpen, setTimelineOpen] = useState(true);
  const [zoom, setZoom] = useState(1);
  const touch = useMediaQuery("(pointer: coarse)");
  const canRender = Boolean(project.analysis && project.transcript) && !active && !busy;
  const working = active && job && job.kind !== "agent";

  const now = screens.find((s) => player.time >= s.start && player.time < s.end);
  const ask = () => {
    const at = timeLabel(player.time);
    onAsk(now?.beat ? `At ${at} (beat ${now.beat}): ` : `At ${at}: `);
  };

  return (
    <section className={cn("flex min-h-0 flex-col overflow-hidden rounded-3xl bg-background", className)}>
      <div className="flex shrink-0 items-center gap-1 px-3 py-2.5 sm:px-4">
        {VIEWS.map(([id, label, Icon]) => (
          <ToolButton key={id} label={label} active={view === id} onClick={() => onView(id)}>
            <Icon className="size-5" />
          </ToolButton>
        ))}
        <span className="ml-2 hidden text-sm font-medium text-muted-foreground sm:inline">
          {VIEWS.find(([id]) => id === view)?.[1]}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <ToolButton label="Render again (free)" onClick={onRender} disabled={!canRender || !last}>
            <RefreshCw className="size-[18px]" />
          </ToolButton>
          {last ? (
            <a
              href={mediaUrl(project.id, last.key, true)}
              className="ml-1 inline-flex h-10 items-center gap-2 rounded-xl bg-foreground px-4 text-sm font-semibold text-background transition-opacity hover:opacity-90"
            >
              <Download className="size-4" /> Download
            </a>
          ) : (
            <span
              title="Your reel appears once it's rendered"
              className="ml-1 inline-flex h-10 cursor-default items-center gap-2 rounded-xl bg-panel-tile px-4 text-sm font-semibold text-muted-foreground"
            >
              <Download className="size-4" /> Download
            </span>
          )}
        </div>
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden bg-frame/40">
        {view === "reel" ? (
          <ReelStage project={project} src={src} player={player} />
        ) : (
          <div className="absolute inset-0 overflow-y-auto overscroll-contain p-4 sm:p-5">
            {view === "script" ? script : <PicturesView project={project} estimate={estimate} />}
          </div>
        )}
        {view === "reel" ? (
          <span className="pointer-events-none absolute left-4 top-3 hidden rounded-lg bg-black/55 px-2.5 py-1 text-xs font-medium text-white backdrop-blur-md sm:block">
            {last ? "Reel · 1080p" : "Preview"}
          </span>
        ) : null}
        {working ? <GeneratingBand step={job.step} progress={job.progress} /> : null}
      </div>

      <div className="grid shrink-0 grid-cols-[1fr_auto_1fr] items-center gap-1 border-t border-border px-2 py-1.5 sm:px-3">
        <div className="flex items-center">
          <ToolButton
            label={timelineOpen ? "Hide the timeline" : "Show the timeline"}
            onClick={() => setTimelineOpen((o) => !o)}
          >
            {timelineOpen ? <ChevronDown className="size-[18px]" /> : <ChevronUp className="size-[18px]" />}
          </ToolButton>
          <span className="mx-1 hidden h-5 w-px bg-border-strong sm:block" />
          <ToolButton label={player.muted ? "Unmute" : "Mute"} onClick={player.toggleMute} disabled={!src}>
            {player.muted ? <VolumeX className="size-[18px]" /> : <Volume2 className="size-[18px]" />}
          </ToolButton>
          <ToolButton label="Ask the chat about this moment" onClick={ask} disabled={!project.transcript || active}>
            <MessageSquarePlus className="size-[18px]" />
          </ToolButton>
        </div>
        <div className="flex items-center gap-2 font-mono text-sm tabular-nums sm:gap-3">
          <span className="text-foreground">{timeLabel(player.time)}</span>
          <button
            type="button"
            onClick={player.toggle}
            disabled={!src}
            aria-label={player.playing ? "Pause" : "Play"}
            className="grid size-10 place-items-center rounded-full text-foreground transition-colors hover:bg-card disabled:opacity-35"
          >
            {player.playing ? <Pause className="size-5 fill-current" /> : <Play className="size-5 fill-current" />}
          </button>
          <span className="text-muted-foreground">{length ? timeLabel(length) : "--:--"}</span>
        </div>
        <label
          className={cn("hidden items-center justify-end pr-1 sm:flex", !timelineOpen && "invisible")}
          title="Zoom the timeline"
        >
          <span className="sr-only">Zoom the timeline</span>
          <input
            type="range"
            min={1}
            max={6}
            step={0.25}
            value={zoom}
            onChange={(e) => setZoom(Number(e.target.value))}
            className="h-1 w-24 cursor-pointer accent-foreground"
          />
        </label>
      </div>

      {timelineOpen ? (
        <Timeline
          project={project}
          screens={screens}
          length={length}
          planned={estimate.seconds}
          time={player.time}
          zoom={zoom}
          onSeek={player.seek}
          note={
            !screens.length
              ? "The timeline fills in once your narration is transcribed"
              : active
                ? "The timeline is read-only while a job runs"
                : `${touch ? "Tap" : "Click"} to move the playhead · edits happen in the chat`
          }
        />
      ) : null}
    </section>
  );
}

function ReelStage({
  project,
  src,
  player,
}: {
  project: Project;
  src: string | null;
  player: ReturnType<typeof usePlayer>;
}) {
  const rendering = jobActive(project) && project.job?.step?.startsWith("Rendering");
  if (!src) {
    return (
      <div className="absolute inset-0 grid place-items-center p-6">
        <div className="flex aspect-[9/16] h-full max-h-[32rem] flex-col items-center justify-center gap-3 rounded-2xl border border-border bg-background/60 p-6 text-center">
          {rendering ? <Loader2 className="size-6 animate-spin text-accent" /> : <Film className="size-6 text-muted-foreground" />}
          <p className="max-w-[14rem] text-sm text-muted-foreground">
            {rendering ? "Rendering your reel…" : "Your reel appears here once it's rendered."}
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="absolute inset-0 flex items-center justify-center p-3 sm:p-4">
      <video
        ref={player.video}
        key={src}
        src={src}
        playsInline
        preload="metadata"
        onClick={player.toggle}
        className="h-full max-h-full w-auto max-w-full cursor-pointer rounded-xl bg-black object-contain shadow-2xl"
      />
    </div>
  );
}

function GeneratingBand({ step, progress }: { step: string; progress: number }) {
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0">
      <div className="h-28 bg-gradient-to-t from-[#2f6df0]/90 via-[#3d7bf7]/45 to-transparent" />
      <div className="absolute inset-x-4 bottom-3 flex items-center gap-2 text-sm font-medium text-white">
        <Sparkles className="size-4 animate-pulse" />
        <span className="truncate">{step || "Generating"}…</span>
        <span className="ml-auto tabular-nums text-white/80">{Math.round((progress || 0) * 100)}%</span>
      </div>
      <div className="h-1 bg-[#2f6df0]">
        <div className="h-full bg-white/80 transition-[width] duration-500" style={{ width: `${Math.round((progress || 0) * 100)}%` }} />
      </div>
    </div>
  );
}

// ---- the timeline ---------------------------------------------------------------------------

const RULER = 28;
const PAD = 16;

function Timeline({
  project,
  screens,
  length,
  planned,
  time,
  zoom,
  onSeek,
  note,
}: {
  project: Project;
  screens: PartScreen[];
  length: number;
  planned: number; // the part's planned length: the ruler's span before there is a reel
  time: number;
  zoom: number;
  onSeek: (t: number) => void;
  note: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const dragging = useRef(false);
  const tap = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);

  // The whole reel fits the width at zoom 1. A phone shows about 40 seconds and scrolls the rest
  // sideways, so the screens stay wide enough for a face.
  const span = Math.max(length || planned, 1);
  const fit = Math.max(width - PAD * 2, 100) / span;
  const perSecond = Math.max(fit * zoom, width && width < 640 ? (width - PAD * 2) / 40 : 0);
  const inner = span * perSecond + PAD * 2;
  const x = (t: number) => PAD + t * perSecond;

  // Keep the playhead in view while the reel plays past the edge of a zoomed timeline.
  useEffect(() => {
    const el = box.current;
    if (!el || inner <= el.clientWidth + 1 || dragging.current) return;
    const px = x(time);
    if (px < el.scrollLeft + 24 || px > el.scrollLeft + el.clientWidth - 24) el.scrollLeft = px - el.clientWidth / 3;
  }, [time, perSecond]); // eslint-disable-line react-hooks/exhaustive-deps

  const at = (clientX: number) => {
    const el = box.current;
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    return Math.max(0, Math.min(span, (clientX - rect.left + el.scrollLeft - PAD) / perSecond));
  };

  const step = perSecond < 7 ? 30 : perSecond < 16 ? 10 : 5; // seconds between labels
  const minor = step / (step === 30 ? 6 : 5);
  const ticks: number[] = [];
  for (let t = 0; t <= span + 0.001; t += minor) ticks.push(Math.round(t * 100) / 100);

  const pictures = project.part_pictures || {};
  const turns = project.transcript?.turns ?? [];

  return (
    <div className="relative shrink-0 border-t border-border">
      <div
        ref={box}
        className="relative h-[10.5rem] overflow-x-auto overflow-y-hidden overscroll-x-contain [scrollbar-width:thin]"
        onPointerDown={(e) => {
          if (!length) return;
          // A finger may be scrolling the timeline: it seeks on a tap, when it lifts.
          if (e.pointerType === "touch") {
            tap.current = { x: e.clientX, y: e.clientY };
            return;
          }
          dragging.current = true;
          (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
          onSeek(at(e.clientX));
        }}
        onPointerMove={(e) => dragging.current && onSeek(at(e.clientX))}
        onPointerUp={(e) => {
          const start = tap.current;
          tap.current = null;
          dragging.current = false;
          if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) < 10) onSeek(at(e.clientX));
        }}
        onPointerCancel={() => {
          tap.current = null;
          dragging.current = false;
        }}
      >
        <div className="relative h-full select-none" style={{ width: Math.max(inner, width) }}>
          {/* ruler */}
          <div className="absolute inset-x-0 top-0" style={{ height: RULER }}>
            {ticks.map((t) => {
              const major = Math.abs(t / step - Math.round(t / step)) < 0.001;
              return major && t > 0 ? (
                <span
                  key={t}
                  className="absolute top-1.5 -translate-x-1/2 text-[11px] font-medium tabular-nums text-muted-foreground"
                  style={{ left: x(t) }}
                >
                  {Math.round(t)}
                </span>
              ) : (
                <span
                  key={t}
                  className="absolute top-3 size-[3px] -translate-x-1/2 rounded-full bg-muted-foreground/40"
                  style={{ left: x(t) }}
                />
              );
            })}
          </div>

          {/* what the reel shows */}
          <div className="absolute inset-x-0" style={{ top: RULER + 4, height: 56 }}>
            {screens.map((s, i) => {
              const left = x(s.start);
              const w = Math.max(2, (s.end - s.start) * perSecond - 3);
              const current = time >= s.start && time < s.end;
              const faces = (s.characters ?? [])
                .slice(0, 2)
                .map((c) => pictureUrl(project, pictures[c]))
                .filter(Boolean)
                .map((url) => ({ url: url as string, round: true }));
              const thing = pictureUrl(project, pictures[s.prop || s.photo || ""]);
              const images = thing ? [...faces, { url: thing, round: false }] : faces;
              // As many 32px pictures as fit, then the label if there is room left for it.
              const shown = images.slice(0, Math.max(0, Math.floor((w - 8) / 36)));
              const room = w - 12 - shown.length * 36;
              const label =
                s.kind === "hook" ? "Hook" : s.kind === "poll" ? "Poll" : s.kind === "cta" ? "End card" : `Beat ${s.beat}`;
              return (
                <div
                  key={`${s.start}-${i}`}
                  title={`${label} · ${seconds(s.start)}–${seconds(s.end)}${s.characters?.length ? ` · ${s.characters.join(", ")}` : ""}${s.prop ? ` · ${s.prop}` : ""}${s.photo ? ` · ${s.photo}` : ""}`}
                  className={cn(
                    "absolute top-0 flex h-full items-center gap-1 overflow-hidden rounded-lg px-1.5",
                    s.kind === "beat" ? "bg-panel-tile" : "bg-accent/15",
                    current && "ring-2 ring-accent",
                  )}
                  style={{ left, width: w }}
                >
                  {shown.map((image) => (
                    <img
                      key={image.url}
                      src={image.url}
                      alt=""
                      className={cn(
                        "size-8 shrink-0 bg-background object-cover",
                        image.round ? "rounded-full object-top" : "rounded-md",
                      )}
                    />
                  ))}
                  {room >= 34 ? (
                    <span className="min-w-0 truncate pl-0.5 text-[11px] font-semibold text-foreground/80">{label}</span>
                  ) : null}
                </div>
              );
            })}
          </div>

          {/* captions */}
          <div className="absolute inset-x-0" style={{ top: RULER + 66, height: 26 }}>
            {turns.map((turn) => {
              const w = Math.max(2, (turn.end - turn.start) * perSecond - 2);
              return (
                <div
                  key={turn.id}
                  title={turn.text}
                  className="absolute top-0 h-full overflow-hidden rounded-md bg-card px-1.5 text-[11px] leading-[26px] text-muted-foreground"
                  style={{ left: x(turn.start), width: w }}
                >
                  {w > 30 ? turn.text : ""}
                </div>
              );
            })}
          </div>

          {/* playhead */}
          {length ? (
            <div className="pointer-events-none absolute bottom-0 top-0" style={{ left: x(Math.min(time, span)) }}>
              <span className="absolute -left-[7px] top-1 size-3.5 rounded-full bg-foreground shadow" />
              <span className="absolute bottom-0 left-[-1px] top-3 w-0.5 bg-foreground" />
            </div>
          ) : null}
        </div>
      </div>
      <p className="pointer-events-none absolute bottom-2 left-1/2 w-max max-w-[90%] -translate-x-1/2 truncate text-center text-xs text-muted-foreground">
        {note}
      </p>
    </div>
  );
}

// ---- the other views ------------------------------------------------------------------------

function Shimmer({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-xl bg-border-strong/60", className)} />;
}

export function ScriptView({ project, onRecord }: { project: Project; onRecord: (index: number) => void }) {
  const part = project.novel!;
  const story = project.story;
  const writing = jobActive(project) && project.job?.kind === "story";
  if (!story) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Chapter {project.chapter}
          {part.chapter_title ? ` · ${part.chapter_title}` : ""}
        </p>
        {writing ? (
          <div className="flex flex-col gap-2">
            <p className="text-sm text-muted-foreground">Muse Spark is reading the chapter and writing the part…</p>
            {[0, 1, 2, 3, 4].map((i) => (
              <Shimmer key={i} className={cn("h-14", i % 2 ? "w-11/12" : "w-full")} />
            ))}
          </div>
        ) : null}
        <p className="relative max-h-[28rem] overflow-hidden whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground [mask-image:linear-gradient(to_bottom,black_60%,transparent)]">
          {part.chapter_text.slice(0, 2400)}
        </p>
      </div>
    );
  }
  const scenes = project.script?.scenes ?? [];
  const beats = new Map(story.beats.map((b) => [b.take, b]));
  const video = project.clips[0];
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-2">
      {video ? (
        <p className="rounded-xl border border-success/30 bg-success/5 px-3 py-2 text-xs text-success">
          Recorded as one video ({seconds(video.duration)}): the takes below are not needed.
        </p>
      ) : null}
      <ol className="flex flex-col gap-2">
        {scenes.map((scene, index) => {
          const beat = beats.get(scene.id);
          const label =
            scene.purpose === "hook"
              ? "Hook · on camera"
              : beat
                ? `Beat ${story.beats.indexOf(beat) + 1} · ${labelFor("act", beat.act)}`
                : scene.purpose.charAt(0).toUpperCase() + scene.purpose.slice(1);
          return (
            <TakeRow
              key={scene.id}
              scene={scene}
              index={index}
              show={beat?.show}
              label={label}
              recordable={!video && !jobActive(project)}
              onRecord={() => onRecord(index)}
            />
          );
        })}
      </ol>
    </div>
  );
}

function TakeRow({
  scene,
  index,
  show,
  label,
  recordable,
  onRecord,
}: {
  scene: Scene;
  index: number;
  show?: { characters?: string[]; prop?: string; photo?: string };
  label: string;
  recordable: boolean;
  onRecord: () => void;
}) {
  const tags = [...(show?.characters ?? []), show?.prop, show?.photo].filter(Boolean) as string[];
  return (
    <li className={cn("rounded-2xl bg-card p-3.5", index === 0 && "ring-1 ring-accent/30")}>
      <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
        <span className="font-semibold text-foreground">{index + 1}</span>
        <span className="flex-1 truncate">{label}</span>
        {scene.take ? (
          <span className="inline-flex items-center gap-1 text-success">
            <Check className="size-3.5" /> {seconds(scene.take.duration)}
          </span>
        ) : null}
        {recordable ? (
          <button type="button" onClick={onRecord} className="min-h-8 rounded-lg px-2 font-semibold text-accent hover:bg-background">
            {scene.take ? "Retake" : "Record"}
          </button>
        ) : null}
      </div>
      <p className="text-[15px] leading-relaxed text-foreground">{scene.lines}</p>
      {tags.length ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {tags.map((t) => (
            <span key={t} className="rounded-md bg-background px-1.5 py-0.5 text-xs text-muted-foreground">
              {t}
            </span>
          ))}
        </div>
      ) : null}
    </li>
  );
}

function PicturesView({ project, estimate }: { project: Project; estimate: PartEstimate }) {
  const pictures = useMemo(() => Object.values(project.part_pictures || {}), [project.part_pictures]);
  const drawing = jobActive(project) && project.job?.step?.startsWith("Drawing");
  if (!pictures.length) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          {drawing
            ? `Muse Image is drawing about ${estimate.pictures} pictures: the characters from the novel's bible, the objects and places this part shows. SAM cuts them out.`
            : "The characters, objects and places are drawn after you record, so they appear when you say them."}
        </p>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {Array.from({ length: estimate.pictures }, (_, i) => (
            <Shimmer key={i} className={cn("aspect-[3/4]", !drawing && "animate-none opacity-40")} />
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="mx-auto grid max-w-4xl grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
      {pictures.map((p) => {
        const url = pictureUrl(project, p);
        return (
          <figure key={p.id} className="flex flex-col gap-1.5">
            {url ? (
              <a href={url} target="_blank" rel="noopener noreferrer" className="overflow-hidden rounded-xl bg-card">
                <img src={url} alt={p.id} loading="lazy" className="aspect-[3/4] w-full object-contain" />
              </a>
            ) : (
              <div className="grid aspect-[3/4] place-items-center rounded-xl bg-card text-danger">
                <AlertCircle className="size-5" />
              </div>
            )}
            <figcaption className="text-xs">
              <span className="font-semibold text-foreground">{p.id.replace(/_/g, " ")}</span>
              <span className="text-muted-foreground"> · {p.kind}</span>
              {p.error ? <span className="block text-danger">{p.error}</span> : null}
            </figcaption>
          </figure>
        );
      })}
    </div>
  );
}
