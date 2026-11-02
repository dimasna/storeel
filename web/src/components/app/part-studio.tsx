import { useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  AlertCircle,
  Check,
  Download,
  FileText,
  Film,
  Images,
  Loader2,
  Mic,
  RotateCcw,
  SlidersHorizontal,
  Sparkles,
  Upload,
} from "lucide-react";
import { api, mediaUrl, novelMediaUrl, upload } from "@/lib/api";
import type { PartEstimate, Project, Scene } from "@/lib/types";
import { jobActive, type UseProject } from "@/lib/use-project";
import { partSteps, recording, type FlowStep } from "@/lib/part-flow";
import { labelFor } from "@/lib/labels";
import { useConfig } from "@/lib/config";
import { Link } from "@/lib/router";
import { expiresIn, megabytes, seconds } from "@/lib/format";
import { useToast } from "@/lib/toast";
import { EASE_OUT } from "@/lib/ease";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ProgressBar } from "@/components/ui/primitives";
import { Recorder } from "./recorder";
import {
  AgentActivity,
  AgentComposer,
  AgentSuggestions,
  AgentThread,
  AssistantBubble,
  PendingActions,
  UserBubble,
} from "./agent-dock";

// A novel part, chat first: the conversation and the six-step checklist on the left, what the
// steps made (the script, the pictures, the reel) on the right. On a phone the preview comes
// first and the chat follows. Pressing Start (or Send on the home page) approves the whole
// first pass: once the last take is recorded, transcribing, drawing and rendering follow on
// their own. Anything after that (a rewrite, new pictures, another render) asks first.

const usd = (value: number) => `$${value.toFixed(2)}`;

/** The editor changed the reel (captions, pictures, style) after it was last rendered. */
function editedSinceRender(project: Project): boolean {
  const last = project.renders[project.renders.length - 1];
  if (!last) return false;
  const rendered = Date.parse(last.created_at);
  return project.agent.messages.some(
    (m) =>
      m.role === "assistant" &&
      Date.parse(m.created_at) > rendered &&
      m.actions.some((a) => a.status === "done" && a.kind !== "render"),
  );
}

function useNow(on: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [on]);
  return now;
}

function clock(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

type Tab = "script" | "pictures" | "reel";

export function PartStudio({ state }: { state: UseProject }) {
  const project = state.project as Project;
  const { toast } = useToast();
  const part = project.novel!;
  const estimate = part.estimate;
  const steps = partSteps(project);
  const rec = recording(project);
  const job = project.job;
  const active = jobActive(project);
  const story = project.story;
  const scenes = project.script?.scenes ?? [];
  const firstPass = project.renders.length === 0;
  const writing = active && job?.kind === "story";
  const processing = active && (job?.kind === "process" || job?.kind === "render");
  // A failed step of the first pass: the checklist offers "Try again" for it.
  const flowFailed = !active && job?.status === "failed" && ["story", "process", "render"].includes(job.kind);
  const now = useNow(active);
  const elapsed = job?.started_at && active ? clock(now - Date.parse(job.started_at)) : "";

  // The recorder: the take on screen, and the one to move on to once it is uploaded.
  const [takeAt, setTakeAt] = useState<number | null>(null);
  const nextTake = useRef<number | null>(null);
  const videoInput = useRef<HTMLInputElement>(null);
  const [rewrite, setRewrite] = useState<string | null>(null);
  const [uploading, setUploading] = useState<number | null>(null); // the video's upload, 0..1

  // Start approved the whole first pass: once every take is in (or one video is), the reel is
  // transcribed, drawn and rendered without asking again. A run the user stopped is not
  // restarted, and a failed one waits for "Try again".
  const autoStarted = useRef(false);
  const stoppedByUser = job?.kind === "process" && job.status === "cancelled";
  const readyToMake =
    firstPass && Boolean(story) && rec.complete && !project.analysis && !active && !flowFailed && !stoppedByUser;
  useEffect(() => {
    if (!rec.complete) autoStarted.current = false; // a retake after a deleted take: start again
    if (!readyToMake || state.busy || autoStarted.current) return;
    autoStarted.current = true;
    state.act(() => api.process(project.id, false, true), "All recorded: transcribing, drawing and rendering…");
  }, [readyToMake, rec.complete, state.busy]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = (brief?: string) =>
    state.act(() => api.writePart(project.id, false, brief), "Muse Spark is writing the part…");

  const record = (index?: number) => {
    const at = index ?? scenes.findIndex((s) => !s.take);
    setTakeAt(at >= 0 ? at : 0);
  };

  const uploadVideo = async (file: File) => {
    setUploading(0);
    try {
      await state.act(
        () => upload(`/api/projects/${project.id}/clips`, file, file.name, setUploading),
        "Video added",
      );
    } finally {
      setUploading(null);
    }
  };

  const retry = (step: FlowStep) => {
    if (step.id === "write" || step.id === "check") return start();
    if (step.id === "render" && project.analysis && job?.kind === "render")
      return state.act(() => api.render(project.id, null), "Rendering…");
    return state.act(() => api.process(project.id, false, firstPass), "Trying again…");
  };

  const tab: Tab = project.renders.length || (processing && job?.step?.startsWith("Rendering"))
    ? "reel"
    : project.part_pictures || (processing && job?.step?.startsWith("Drawing"))
      ? "pictures"
      : "script";

  // Before the reel exists the message box asks the writer for a rewrite; after it, the editor.
  let composer: ReactNode;
  if (!story && !writing) {
    composer = (
      <AgentComposer
        project={project}
        state={state}
        placeholder="Anything to focus on? (optional)"
        sendLabel={`Write · ≈ ${usd(estimate.total_usd)}`}
        onSend={async (message) => Boolean(await start(message))}
      />
    );
  } else if (writing) {
    composer = <AgentComposer project={project} state={state} disabledNote="Muse Spark is writing the part…" />;
  } else if (processing) {
    composer = <AgentComposer project={project} state={state} disabledNote="Making the reel. You can ask for changes once it's done." />;
  } else if (!project.transcript) {
    composer = (
      <AgentComposer
        project={project}
        state={state}
        placeholder="Ask for a rewrite, e.g. “a stronger hook”"
        onSend={async (message) => {
          setRewrite(message);
          return true;
        }}
      />
    );
  } else {
    composer = <AgentComposer project={project} state={state} />;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <Link to={`/n/${part.id}`} className="w-fit text-sm text-muted-foreground transition-colors hover:text-foreground">
            ← {part.title}
          </Link>
          <h1 className="text-xl font-bold leading-tight tracking-tight sm:text-2xl">{project.title}</h1>
        </div>
        <Link
          to={`/p/${project.id}/details`}
          className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-xl border border-border-strong px-3 text-sm font-semibold text-foreground transition-colors hover:border-accent/60"
        >
          <SlidersHorizontal className="size-4" /> Details
        </Link>
      </div>

      <div className="grid gap-5 lg:h-[calc(100dvh-9.5rem)] lg:min-h-[34rem] lg:grid-cols-[minmax(0,27rem)_minmax(0,1fr)]">
        {/* Chat */}
        <section className="order-2 flex min-h-0 flex-col rounded-3xl border border-border bg-card/60 lg:order-1">
          <div className="flex-1 overflow-y-auto overscroll-contain p-4">
            <div className="flex flex-col gap-4">
              <UserBubble>
                Make part {project.chapter} from chapter {project.chapter}
                {part.chapter_title ? `: ${part.chapter_title}` : ""} ({part.chapter_text.length.toLocaleString()} characters).
                {project.brief ? `\n“${project.brief}”` : ""}
              </UserBubble>

              <Plan project={project} estimate={estimate} />

              {!story && !active && !(job?.status === "failed" && job.kind === "story") ? (
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="primary" className="h-11" disabled={state.busy} onClick={() => start()}>
                    <Sparkles className="size-4" /> Start · ≈ {usd(estimate.total_usd)}
                  </Button>
                  <span className="text-xs text-muted-foreground">Or type a request below first.</span>
                </div>
              ) : null}

              <Checklist project={project} steps={steps} elapsed={elapsed} onRetry={retry} state={state} />

              {story && !writing ? <Written project={project} /> : null}

              {story && !writing && !rec.complete ? (
                <YourTurn
                  project={project}
                  uploading={uploading}
                  onRecord={() => record()}
                  onUpload={() => videoInput.current?.click()}
                />
              ) : null}

              {story && rec.complete && !active && !flowFailed && (!project.transcript || !project.analysis || firstPass) ? (
                <ContinueCard
                  project={project}
                  estimate={estimate}
                  firstPass={firstPass}
                  busy={state.busy}
                  onContinue={() => state.act(() => api.process(project.id, false, true), "Transcribing, drawing and rendering…")}
                />
              ) : null}

              {rewrite !== null ? (
                <RewriteCard
                  project={project}
                  brief={rewrite}
                  estimate={estimate}
                  busy={state.busy}
                  onCancel={() => setRewrite(null)}
                  onConfirm={async () => {
                    if (await start(rewrite)) setRewrite(null);
                  }}
                />
              ) : null}

              {project.renders.length ? <ReelReady project={project} estimate={estimate} /> : null}

              {project.transcript && project.renders.length && !project.agent.messages.length && !active ? (
                <AgentSuggestions project={project} state={state} intro="Want changes? Ask in your own words, for example:" />
              ) : null}

              {project.agent.messages.length ? (
                <AgentThread messages={project.agent.messages} applying={active && job?.kind === "agent_apply"} />
              ) : null}
              <PendingActions project={project} state={state} />
              <AgentActivity project={project} state={state} />
              {editedSinceRender(project) && !active ? (
                <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-accent/40 bg-accent/5 p-3">
                  <span className="flex-1 text-sm text-foreground">Your changes aren't in the reel yet.</span>
                  <Button
                    variant="primary"
                    className="h-11"
                    disabled={state.busy}
                    onClick={() => state.act(() => api.render(project.id, null), "Rendering…")}
                  >
                    <Film className="size-4" /> Render again · free
                  </Button>
                </div>
              ) : null}
              <ScrollAnchor project={project} />
            </div>
          </div>
          <div className="sticky bottom-0 z-10 shrink-0 rounded-b-3xl border-t border-border bg-card/95 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur-xl lg:static">
            {composer}
          </div>
        </section>

        {/* Preview */}
        <section className="order-1 min-h-0 lg:order-2">
          <Preview
            key={tab}
            project={project}
            initial={tab}
            estimate={estimate}
            onRecord={record}
          />
        </section>
      </div>

      <input
        ref={videoInput}
        type="file"
        accept="video/*"
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) uploadVideo(file);
        }}
      />

      {takeAt !== null && scenes[takeAt] ? (
        <Recorder
          key={takeAt}
          scene={scenes[takeAt]}
          index={takeAt}
          total={scenes.length}
          onTake={async (blob, name, onProgress) => {
            const scene = scenes[takeAt];
            const updated = await upload(`/api/projects/${project.id}/scenes/${scene.id}/take`, blob, name, onProgress);
            state.set(updated);
            const left = (updated.script?.scenes ?? []).filter((s) => !s.take).length;
            toast(left ? `Take ${takeAt + 1} saved · ${left} to go` : "Every take is recorded", "ok");
            const after = (updated.script?.scenes ?? []).findIndex((s, i) => i > takeAt && !s.take);
            const anyLeft = (updated.script?.scenes ?? []).findIndex((s) => !s.take);
            nextTake.current = after >= 0 ? after : anyLeft >= 0 ? anyLeft : null;
          }}
          onClose={() => {
            setTakeAt(nextTake.current);
            nextTake.current = null;
          }}
        />
      ) : null}
    </div>
  );
}

// ---- chat pieces ----------------------------------------------------------------------------

function Plan({ project, estimate }: { project: Project; estimate: PartEstimate }) {
  const part = project.novel!;
  const transcribe = estimate.transcribe_usd < 0.005 ? "under $0.01" : usd(estimate.transcribe_usd);
  const minutes = Math.max(1, Math.round(estimate.seconds / 30) / 2);
  return (
    <AssistantBubble>
      {`I'll make part ${project.chapter} as a teaser of about ${minutes} minute${minutes === 1 ? "" : "s"}: a hook on camera, the story in short beats over pictures, a poll and a call to action.\n`}
      {`Voice: ${labelFor("narration", part.narration)}. Pictures: ${labelFor("visual_style", part.visual_style)}. Language: ${labelFor("novel_language", part.language)}.\n\n`}
      {"Then it's your turn to record it from a teleprompter, line by line. I transcribe your narration, draw the characters and scenes, and render the reel.\n\n"}
      <span className="text-muted-foreground">
        {`Writing and checking take 2 to 4 minutes. Estimated ≈ ${usd(estimate.total_usd)} at Meta's list prices: writing ${usd(estimate.write_usd)}, about ${estimate.pictures} pictures ${usd(estimate.draw_usd)}, transcription ${transcribe}. Rendering is free.`}
      </span>
    </AssistantBubble>
  );
}

function StepIcon({ step, index }: { step: FlowStep; index: number }) {
  const base = "grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold";
  if (step.state === "done")
    return (
      <span className={cn(base, "bg-success/15 text-success")}>
        <Check className="size-4" />
      </span>
    );
  if (step.state === "active")
    return (
      <span className={cn(base, "bg-accent/15 text-accent")}>
        <Loader2 className="size-4 animate-spin" />
      </span>
    );
  if (step.state === "yours")
    return (
      <span className={cn(base, "bg-warning/15 text-warning")}>
        <Mic className="size-4" />
      </span>
    );
  if (step.state === "failed")
    return (
      <span className={cn(base, "bg-danger/15 text-danger")}>
        <AlertCircle className="size-4" />
      </span>
    );
  return <span className={cn(base, "border border-border-strong text-muted-foreground")}>{index + 1}</span>;
}

function Checklist({
  project,
  steps,
  elapsed,
  onRetry,
  state,
}: {
  project: Project;
  steps: FlowStep[];
  elapsed: string;
  onRetry: (step: FlowStep) => void;
  state: UseProject;
}) {
  const job = project.job;
  const running = steps.find((s) => s.state === "active");
  const spent = project.usage.estimated_usd;
  return (
    <div className="rounded-2xl border border-border bg-background/70 p-2">
      <ol className="flex flex-col">
        {steps.map((step, index) => (
          <li
            key={step.id}
            className={cn(
              "flex gap-3 rounded-xl px-2 py-2",
              (step.state === "active" || step.state === "yours") && "bg-card",
            )}
          >
            <StepIcon step={step} index={index} />
            <div className="min-w-0 flex-1 pt-0.5">
              <p
                className={cn(
                  "text-sm leading-snug",
                  step.state === "todo" ? "text-muted-foreground" : "text-foreground",
                  (step.state === "active" || step.state === "yours") && "font-semibold",
                )}
              >
                {step.label}
              </p>
              {step.detail ? (
                <p className={cn("mt-0.5 text-xs leading-snug", step.state === "failed" ? "text-danger" : "text-muted-foreground")}>
                  {step.detail}
                </p>
              ) : null}
              {step.state === "active" && job ? (
                <div className="mt-2 flex items-center gap-2">
                  <ProgressBar value={job.progress || 0} />
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{elapsed}</span>
                </div>
              ) : null}
              {step.state === "failed" ? (
                <Button size="sm" className="mt-2" disabled={state.busy} onClick={() => onRetry(step)}>
                  <RotateCcw className="size-3.5" /> Try again
                </Button>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
      <div className="flex items-center justify-between gap-2 px-2 pb-1 pt-2 text-xs text-muted-foreground">
        <span>Spent so far ≈ {usd(spent)}</span>
        {running && job && !job.cancel_requested ? (
          <button
            type="button"
            onClick={() => state.act(() => api.cancelJob(job.id), "Stopping…")}
            className="min-h-8 px-1 font-semibold hover:text-foreground"
          >
            Stop
          </button>
        ) : null}
      </div>
    </div>
  );
}

function Written({ project }: { project: Project }) {
  const story = project.story!;
  const notes = story.problems;
  const fixed = story.review_found ?? 0;
  let check: string;
  if (notes.length)
    check = `The storyboard check left ${notes.length} note${notes.length > 1 ? "s" : ""}: ${notes.slice(0, 2).join("; ")}${notes.length > 2 ? "…" : ""}`;
  else if (fixed)
    check = `The storyboard check found ${fixed} picture${fixed > 1 ? "s" : ""} that didn't match the chapter, and I rewrote ${fixed > 1 ? "them" : "it"}.`;
  else check = "The storyboard check found nothing to fix: every picture matches what the words say.";
  return (
    <AssistantBubble>
      {`Part ${story.part} is written: “${story.chapter_title}”, ${story.beats.length} beats. ${check}`}
      {project.brief ? `\nI wrote it with your request in mind: “${project.brief}”.` : ""}
    </AssistantBubble>
  );
}

function YourTurn({
  project,
  uploading,
  onRecord,
  onUpload,
}: {
  project: Project;
  uploading: number | null;
  onRecord: () => void;
  onUpload: () => void;
}) {
  const rec = recording(project);
  const next = (project.script?.scenes ?? []).findIndex((s) => !s.take);
  return (
    <div className="rounded-2xl border border-warning/40 bg-warning/5 p-4">
      <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <Mic className="size-4 text-warning" /> Your turn: record the part
      </p>
      <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
        {rec.takes} short takes, each a line or two read from the teleprompter in one go.{" "}
        {rec.recorded ? `${rec.recorded} of ${rec.takes} done. ` : ""}
        After the last one, the reel is made on its own. Or upload one video of you reading the
        whole part.
      </p>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-border-strong">
        <div
          className="h-full rounded-full bg-warning transition-[width] duration-300"
          style={{ width: `${rec.takes ? Math.round((rec.recorded / rec.takes) * 100) : 0}%` }}
        />
      </div>
      {uploading !== null ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-4 shrink-0 animate-spin text-accent" />
          <span className="shrink-0">Uploading your video</span>
          <ProgressBar value={uploading} />
          <span className="shrink-0 tabular-nums">{Math.round(uploading * 100)}%</span>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="primary" className="h-11" onClick={onRecord}>
            <Mic className="size-4" /> {rec.recorded ? `Record take ${next + 1}` : "Start recording"}
          </Button>
          <Button className="h-11" onClick={onUpload}>
            <Upload className="size-4" /> Upload one video
          </Button>
        </div>
      )}
    </div>
  );
}

function ContinueCard({
  estimate,
  firstPass,
  busy,
  onContinue,
}: {
  project: Project;
  estimate: PartEstimate;
  firstPass: boolean;
  busy: boolean;
  onContinue: () => void;
}) {
  const cost = firstPass
    ? `≈ ${usd(estimate.draw_usd + estimate.transcribe_usd)}`
    : "usually a few cents: only what changed is drawn again";
  return (
    <div className="rounded-2xl border border-accent/40 bg-accent/5 p-4">
      <p className="text-sm text-foreground">
        {firstPass
          ? "Everything is recorded. Transcribe it, draw the pictures and render the reel?"
          : "Your recording changed. Transcribe it again, draw what changed and render a new reel?"}
      </p>
      <Button variant="primary" className="mt-3 h-11" disabled={busy} onClick={onContinue}>
        Make the reel · {cost}
      </Button>
    </div>
  );
}

function RewriteCard({
  project,
  brief,
  estimate,
  busy,
  onCancel,
  onConfirm,
}: {
  project: Project;
  brief: string;
  estimate: PartEstimate;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const rec = recording(project);
  const lost = rec.video ? "your uploaded video no longer matches it" : rec.recorded ? `the ${rec.recorded} recorded take${rec.recorded > 1 ? "s are" : " is"} deleted` : "";
  return (
    <div className="flex flex-col gap-3">
      <UserBubble>{brief}</UserBubble>
      <div className="rounded-2xl border border-accent/40 bg-accent/5 p-4">
        <p className="text-sm text-foreground">
          Rewrite the part with this request? ≈ {usd(estimate.write_usd)}
          {lost ? `, and ${lost}.` : "."}
        </p>
        <div className="mt-3 flex gap-2">
          <Button variant="primary" className="h-11 flex-1" disabled={busy} onClick={onConfirm}>
            Rewrite · ≈ {usd(estimate.write_usd)}
          </Button>
          <Button variant="ghost" className="h-11" disabled={busy} onClick={onCancel}>
            Keep this one
          </Button>
        </div>
      </div>
    </div>
  );
}

function ReelReady({ project, estimate }: { project: Project; estimate: PartEstimate }) {
  const config = useConfig();
  const ttl = config.ttl_hours ?? 0;
  const last = project.renders[project.renders.length - 1];
  return (
    <div className="flex flex-col items-start gap-2">
      <AssistantBubble>
        {`Your reel is ready: ${seconds(last.duration)}, ${megabytes(last.size)}. `}
        {ttl ? `It's kept for ${ttl} hours (${expiresIn(project.updated_at, ttl)}), so download it. ` : ""}
        {`Spent ≈ ${usd(project.usage.estimated_usd)} (estimated ${usd(estimate.total_usd)}).`}
      </AssistantBubble>
      <a
        href={mediaUrl(project.id, last.key, true)}
        className="inline-flex min-h-11 items-center gap-2 rounded-xl px-4 text-sm font-semibold text-white"
        style={{ background: "var(--gradient-accent)" }}
      >
        <Download className="size-4" /> Download the reel
      </a>
    </div>
  );
}

/** Keeps the newest message in view as the conversation grows. */
function ScrollAnchor({ project }: { project: Project }) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const key = [
    project.agent.messages.length,
    project.story ? 1 : 0,
    project.renders.length,
    project.job?.id,
    project.job?.status,
  ].join(":");
  const first = useRef(true);
  useEffect(() => {
    const el = ref.current;
    const list = el?.closest(".overflow-y-auto");
    if (!el || !list || list.scrollHeight <= list.clientHeight) return;
    list.scrollTo({ top: list.scrollHeight, behavior: first.current || reduce ? "auto" : "smooth" });
    first.current = false;
  }, [key, reduce]);
  return <div ref={ref} />;
}

// ---- preview ------------------------------------------------------------------------------

function Preview({
  project,
  initial,
  estimate,
  onRecord,
}: {
  project: Project;
  initial: Tab;
  estimate: PartEstimate;
  onRecord: (index: number) => void;
}) {
  const [tab, setTab] = useState<Tab>(initial);
  const tabs: [Tab, string, typeof FileText][] = [
    ["script", "Script", FileText],
    ["pictures", "Pictures", Images],
    ["reel", "Reel", Film],
  ];
  return (
    <div className="flex h-full min-h-0 flex-col rounded-3xl border border-border bg-card/60">
      <div className="flex shrink-0 gap-1 border-b border-border p-2" role="tablist">
        {tabs.map(([id, label, Icon]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn(
              "inline-flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-xl text-sm font-semibold transition-colors",
              tab === id ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-4" /> {label}
          </button>
        ))}
      </div>
      <div className="max-h-[72dvh] min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 lg:max-h-none">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.18, ease: EASE_OUT }}
          >
            {tab === "script" ? <ScriptPreview project={project} onRecord={onRecord} /> : null}
            {tab === "pictures" ? <PicturesPreview project={project} estimate={estimate} /> : null}
            {tab === "reel" ? <ReelPreview project={project} /> : null}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

function Shimmer({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-xl bg-border-strong/60", className)} />;
}

function ScriptPreview({ project, onRecord }: { project: Project; onRecord: (index: number) => void }) {
  const part = project.novel!;
  const story = project.story;
  const writing = jobActive(project) && project.job?.kind === "story";
  if (!story) {
    return (
      <div className="flex flex-col gap-3">
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
        <p className="relative max-h-80 overflow-hidden whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground [mask-image:linear-gradient(to_bottom,black_60%,transparent)]">
          {part.chapter_text.slice(0, 1600)}
        </p>
      </div>
    );
  }

  const scenes = project.script?.scenes ?? [];
  const beats = new Map(story.beats.map((b) => [b.take, b]));
  const video = project.clips[0];
  return (
    <div className="flex flex-col gap-2">
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
                ? `Beat · ${labelFor("act", beat.act)}`
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
    <li className={cn("rounded-2xl border bg-background p-3", index === 0 ? "border-accent/30" : "border-border")}>
      <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
        <span className="font-semibold text-foreground">{index + 1}</span>
        <span className="flex-1 truncate">{label}</span>
        {scene.take ? (
          <span className="inline-flex items-center gap-1 text-success">
            <Check className="size-3.5" /> {seconds(scene.take.duration)}
          </span>
        ) : null}
        {recordable ? (
          <button
            type="button"
            onClick={onRecord}
            className="min-h-8 rounded-lg px-2 font-semibold text-accent hover:bg-card"
          >
            {scene.take ? "Retake" : "Record"}
          </button>
        ) : null}
      </div>
      <p className="text-sm leading-relaxed text-foreground">{scene.lines}</p>
      {tags.length ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {tags.map((t) => (
            <span key={t} className="rounded-md bg-card px-1.5 py-0.5 text-xs text-muted-foreground">
              {t}
            </span>
          ))}
        </div>
      ) : null}
    </li>
  );
}

function PicturesPreview({ project, estimate }: { project: Project; estimate: PartEstimate }) {
  const pictures = Object.values(project.part_pictures || {});
  const drawing = jobActive(project) && project.job?.step?.startsWith("Drawing");
  if (!pictures.length) {
    return (
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          {drawing
            ? `Muse Image is drawing about ${estimate.pictures} pictures: the characters from the novel's bible, the objects and places this part shows. SAM cuts them out.`
            : "The characters, objects and places are drawn after you record, so they appear when you say them."}
        </p>
        <div className="grid grid-cols-3 gap-2">
          {Array.from({ length: estimate.pictures }, (_, i) => (
            <Shimmer key={i} className={cn("aspect-[3/4]", !drawing && "animate-none opacity-40")} />
          ))}
        </div>
      </div>
    );
  }
  const url = (p: (typeof pictures)[number]) =>
    p.scope === "novel" && project.novel ? novelMediaUrl(project.novel.id, p.key!) : mediaUrl(project.id, p.key!);
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {pictures.map((p) => (
        <figure key={p.id} className="flex flex-col gap-1.5">
          {p.key ? (
            <a href={url(p)} target="_blank" rel="noopener noreferrer" className="overflow-hidden rounded-xl border border-border bg-background">
              <img src={url(p)} alt={p.id} loading="lazy" className="aspect-[3/4] w-full object-contain" />
            </a>
          ) : (
            <div className="grid aspect-[3/4] place-items-center rounded-xl border border-danger/40 bg-background text-danger">
              <AlertCircle className="size-5" />
            </div>
          )}
          <figcaption className="text-xs">
            <span className="font-semibold text-foreground">{p.id.replace(/_/g, " ")}</span>
            <span className="text-muted-foreground"> · {p.kind}</span>
            {p.error ? <span className="block text-danger">{p.error}</span> : null}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

function ReelPreview({ project }: { project: Project }) {
  const last = project.renders[project.renders.length - 1];
  const rendering = jobActive(project) && project.job?.step?.startsWith("Rendering");
  if (!last) {
    return (
      <div className="mx-auto flex aspect-[9/16] max-h-[56dvh] w-full max-w-[18rem] flex-col items-center justify-center gap-3 rounded-3xl border border-border bg-background p-6 text-center">
        {rendering ? <Loader2 className="size-6 animate-spin text-accent" /> : <Film className="size-6 text-muted-foreground" />}
        <p className="text-sm text-muted-foreground">
          {rendering
            ? `Rendering… ${Math.round((project.job?.progress || 0) * 100)}%`
            : "Your reel appears here once it's rendered."}
        </p>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center gap-3">
      <video
        key={last.key}
        src={mediaUrl(project.id, last.key)}
        controls
        playsInline
        preload="metadata"
        className="aspect-[9/16] max-h-[54dvh] w-auto max-w-full rounded-2xl border border-border bg-black object-contain lg:max-h-[calc(100dvh-19rem)]"
      />
      <div className="flex w-full max-w-sm items-center justify-between gap-2 text-sm">
        <span className="text-muted-foreground">
          {seconds(last.duration)} · {megabytes(last.size)}
        </span>
        <a
          href={mediaUrl(project.id, last.key, true)}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-border-strong px-4 font-semibold transition-colors hover:border-accent/60"
        >
          <Download className="size-4" /> Download
        </a>
      </div>
    </div>
  );
}
