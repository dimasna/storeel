import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  AlertCircle,
  ArrowUp,
  ChevronLeft,
  CircleCheck,
  CircleDashed,
  Download,
  Film,
  Loader2,
  MessageSquare,
  Mic,
  Plus,
  RotateCcw,
  SlidersHorizontal,
  Sparkles,
  Square,
  SquareSlash,
  Upload,
  Zap,
} from "lucide-react";
import { api, mediaUrl, upload } from "@/lib/api";
import type { PartEstimate, Project } from "@/lib/types";
import { jobActive, type UseProject } from "@/lib/use-project";
import { partSteps, recording, type FlowStep } from "@/lib/part-flow";
import { labelFor } from "@/lib/labels";
import { useConfig } from "@/lib/config";
import { useMediaQuery } from "@/lib/use-media-query";
import { Link } from "@/lib/router";
import { expiresIn, megabytes, seconds } from "@/lib/format";
import { useToast } from "@/lib/toast";
import { EASE_OUT } from "@/lib/ease";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ProgressBar } from "@/components/ui/primitives";
import { useBareFrame } from "./app-shell";
import { Recorder } from "./recorder";
import { PartEditor, ScriptView, type EditorView } from "./part-editor";
import {
  AgentActivity,
  AgentThread,
  AssistantBubble,
  ChatLook,
  PendingActions,
  UserBubble,
  agentSuggestions,
} from "./agent-dock";

// A novel part, after OpusClip's editor: the chat (the request, the plan, a checklist of the
// six steps as they run, then the editor's conversation) in one panel, and the editor (the
// reel, its script or its pictures, a player and a timeline) in another. On a phone the two
// panels are tabs: the chat until the first reel is rendered, then the editor. Start (or Send
// on the home page) approves the whole first pass: once the last take is recorded,
// transcribing, drawing and rendering follow on their own. Anything after that (a rewrite, new
// pictures, another render) asks first.

type PhoneTab = "chat" | "editor";

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

/** "1m 05s", as OpusClip counts a run. */
function elapsedLabel(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(total / 60);
  return m ? `${m}m ${String(total % 60).padStart(2, "0")}s` : `${total}s`;
}

/** What the running job is doing, in a sentence for the chat. */
function statusLine(project: Project): string {
  const job = project.job;
  const step = job?.step ?? "";
  if (!job) return "";
  if (job.kind === "story") {
    if (step.startsWith("Checking")) return "Checking every picture against the chapter…";
    if (step.startsWith("Fixing")) return "Fixing what the check found. Almost there…";
    if (step.startsWith("Making")) return "Making the part from your video…";
    return "Muse Spark is writing the part. This usually takes a minute or two…";
  }
  if (job.kind === "process") {
    if (step.startsWith("Transcribing")) return "Muse Voice Transcribe is listening to your narration…";
    if (step.startsWith("Drawing")) return "Drawing the characters and scenes. This usually takes a minute or two…";
    if (step.startsWith("Finding")) return "Finding your face, so no picture covers it…";
    if (step.startsWith("Rendering")) return "Rendering the reel: captions, pictures and your voice…";
    return "Preparing your recording…";
  }
  if (job.kind === "render") return "Rendering the reel: captions, pictures and your voice…";
  if (job.kind === "agent_apply") return job.step ? `${job.step}…` : "Running the approved changes…";
  return "";
}

/** The newest lines of the running job's log, the way an agent thinks out loud. */
function thinking(project: Project): string[] {
  const log = project.job?.log ?? "";
  return log
    .split("\n")
    .map((line) => line.replace(/^\d\d:\d\d:\d\d\s+/, "").trim())
    .filter((line) => line && !line.startsWith("==") && !line.startsWith("request:"))
    .slice(-2)
    .map((line) => (line.length > 120 ? `${line.slice(0, 117)}…` : line));
}

export function PartStudio({ state }: { state: UseProject }) {
  useBareFrame();
  const project = state.project as Project;
  const { toast } = useToast();
  const desktop = useMediaQuery("(min-width: 1024px)");
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
  const making = active && (job?.kind === "process" || job?.kind === "render" || job?.kind === "agent_apply");
  // A failed step of the first pass: the checklist offers "Try again" for it.
  const flowFailed = !active && job?.status === "failed" && ["story", "process", "render"].includes(job.kind);
  const now = useNow(active);
  const elapsed = job?.started_at && active ? elapsedLabel(now - Date.parse(job.started_at)) : "";

  // The recorder: the take on screen, and the one to move on to once it is uploaded.
  const [takeAt, setTakeAt] = useState<number | null>(null);
  const nextTake = useRef<number | null>(null);
  const videoInput = useRef<HTMLInputElement>(null);
  const [rewrite, setRewrite] = useState<string | null>(null);
  const [uploading, setUploading] = useState<number | null>(null); // the video's upload, 0..1
  const [draft, setDraft] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);

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

  // The editor shows what the flow is on: the script while it is written and recorded, the
  // pictures while they are drawn, the reel once it is rendering or done.
  const autoView: EditorView =
    project.renders.length || (making && job?.step?.startsWith("Rendering"))
      ? "reel"
      : project.part_pictures || (making && job?.step?.startsWith("Drawing"))
        ? "pictures"
        : "script";
  const [view, setView] = useState<EditorView>(autoView);
  useEffect(() => setView(autoView), [autoView]);

  // On a phone: the chat while the first pass runs, the editor once there is a reel. The first
  // reel switches to the editor on its own, the way the editor switches to it on a desktop.
  const [tab, setTab] = useState<PhoneTab>(() => (project.renders.length ? "editor" : "chat"));
  const rendered = useRef(project.renders.length);
  useEffect(() => {
    if (!rendered.current && project.renders.length) setTab("editor");
    rendered.current = project.renders.length;
  }, [project.renders.length]);

  const start = (brief?: string) =>
    state.act(() => api.writePart(project.id, false, brief), "Muse Spark is writing the part…");

  const record = (index?: number) => {
    const at = index ?? scenes.findIndex((s) => !s.take);
    setTakeAt(at >= 0 ? at : 0);
  };

  const uploadVideo = async (file: File) => {
    setUploading(0);
    try {
      await state.act(() => upload(`/api/projects/${project.id}/clips`, file, file.name, setUploading), "Video added");
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

  const renderAgain = () => state.act(() => api.render(project.id, null), "Rendering…");

  const ask = (text: string) => {
    setTab("chat");
    setDraft((d) => (d.trim() ? `${d.trim()} ${text}` : text));
    window.setTimeout(() => {
      const el = input.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    }, 0);
  };

  // What the message box does now: before the part is written it is the writer's brief, while
  // the part waits to be recorded it asks for a rewrite, once the reel exists it is the editor.
  let mode: { placeholder: string; ideas: string[]; send: (message: string) => Promise<boolean>; locked?: string };
  if (writing) mode = { placeholder: "Muse Spark is writing the part…", ideas: [], send: async () => false, locked: "writing" };
  else if (making)
    mode = { placeholder: "Making the reel. Ask for changes once it's done.", ideas: [], send: async () => false, locked: "making" };
  else if (!story)
    mode = {
      placeholder: "Anything the part should focus on? Type / for ideas",
      ideas: ["End on the biggest twist of the chapter", "Focus on the romance", "Quote the main character more"],
      send: async (message) => Boolean(await start(message)),
    };
  else if (!project.transcript)
    mode = {
      placeholder: "Ask for a rewrite, e.g. a stronger hook. Type / for ideas",
      ideas: ["A stronger hook", "End on a bigger cliffhanger", "Fewer beats, faster pace", "Quote the characters more"],
      send: async (message) => {
        setRewrite(message);
        return true;
      },
    };
  else
    mode = {
      placeholder: "Ask for a change, or type / for ideas",
      ideas: agentSuggestions(project),
      send: async (message) => Boolean(await state.act(() => api.agentSend(project.id, message))),
    };

  const chat = (
    <ChatLook.Provider value="plain">
      <section
        className={cn(
          "flex min-h-0 flex-1 flex-col rounded-3xl bg-background lg:h-full lg:w-[29rem] lg:flex-none xl:w-[31rem]",
          !desktop && tab !== "chat" && "hidden",
        )}
      >
        <header className="flex shrink-0 items-center gap-1.5 px-3 pb-1 pt-3 sm:px-4">
          <Link
            to={`/n/${part.id}`}
            title={`Back to ${part.title}`}
            aria-label={`Back to ${part.title}`}
            className="grid size-9 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-card hover:text-foreground"
          >
            <ChevronLeft className="size-5" />
          </Link>
          <h1 title={project.title} className="min-w-0 flex-1 truncate text-lg font-semibold tracking-tight">
            {story ? `Part ${story.part}: ${story.chapter_title}` : project.title.replace(/^.* - (Part \d+)/, "$1")}
          </h1>
          {project.agent.messages.length ? (
            <button
              type="button"
              title="New chat (your edits stay)"
              aria-label="New chat"
              disabled={active}
              onClick={() =>
                confirm("Start a new chat? The conversation is cleared; your edits stay.") &&
                state.act(() => api.agentClear(project.id))
              }
              className="grid size-9 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-card hover:text-foreground disabled:opacity-40"
            >
              <RotateCcw className="size-[18px]" />
            </button>
          ) : null}
          <Link
            to={`/p/${project.id}/details`}
            title="Every setting and section"
            aria-label="Details"
            className="grid size-9 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-card hover:text-foreground"
          >
            <SlidersHorizontal className="size-[18px]" />
          </Link>
        </header>

        <div className="flex-1 overflow-y-auto overscroll-contain px-4 pb-4 pt-2 sm:px-5">
          <div className="flex flex-col gap-5">
            <UserBubble>
              Make part {project.chapter} from chapter {project.chapter}
              {part.chapter_title ? `: ${part.chapter_title}` : ""} ({part.chapter_text.length.toLocaleString()} characters).
              {project.brief ? `\n“${project.brief}”` : ""}
            </UserBubble>

            <Plan project={project} estimate={estimate} />

            {!story && !active && !(job?.status === "failed" && job.kind === "story") ? (
              <div className="flex flex-wrap items-center gap-3 px-1">
                <Button variant="primary" className="h-11" disabled={state.busy} onClick={() => start()}>
                  <Sparkles className="size-4" /> Start · ≈ {usd(estimate.total_usd)}
                </Button>
                <span className="text-xs text-muted-foreground">Or type a request below first.</span>
              </div>
            ) : null}

            <Checklist project={project} steps={steps} onRetry={retry} busy={state.busy} />

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

            {project.agent.messages.length ? (
              <AgentThread messages={project.agent.messages} applying={active && job?.kind === "agent_apply"} />
            ) : null}
            <PendingActions project={project} state={state} />
            <AgentActivity project={project} state={state} />
            {editedSinceRender(project) && !active ? (
              <div className="flex flex-wrap items-center gap-3 rounded-2xl bg-card p-3.5">
                <span className="flex-1 text-sm text-foreground">Your changes aren't in the reel yet.</span>
                <Button variant="primary" className="h-10" disabled={state.busy} onClick={renderAgain}>
                  <Film className="size-4" /> Render again · free
                </Button>
              </div>
            ) : null}
            {active && job && job.kind !== "agent" ? (
              <div className="flex items-start gap-3 px-1 text-[15px] leading-relaxed text-muted-foreground">
                <Sparkles className="mt-1 size-4 shrink-0 animate-pulse text-accent" />
                <span className="shrink-0 tabular-nums text-foreground/80">{elapsed}</span>
                <span>· {statusLine(project)}</span>
              </div>
            ) : null}
            <ScrollAnchor project={project} shown={desktop || tab === "chat"} />
          </div>
        </div>

        <div className="shrink-0 rounded-b-3xl px-3 pb-3 pt-1">
          <StudioComposer
            inputRef={input}
            value={draft}
            onChange={setDraft}
            placeholder={mode.placeholder}
            locked={Boolean(mode.locked)}
            busy={state.busy}
            ideas={mode.ideas}
            onSend={mode.send}
            spent={story ? `${usd(project.usage.estimated_usd)}` : `≈ ${usd(estimate.total_usd)}`}
            spentTitle={story ? "Spent on this part at Meta's list prices" : "What the first pass is estimated to cost"}
            canUpload={Boolean(story) && !active && !rec.video}
            onUpload={() => videoInput.current?.click()}
            stop={
              active && job && !job.cancel_requested
                ? () => state.act(() => api.cancelJob(job.id), "Stopping…")
                : undefined
            }
          />
        </div>
      </section>
    </ChatLook.Provider>
  );

  return (
    <div className="flex h-[calc(100dvh-4rem)] flex-col gap-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] lg:h-full lg:flex-row lg:pb-0">
      {desktop ? null : <PhoneTabs tab={tab} onTab={setTab} working={active && job?.kind !== "agent"} />}
      {chat}
      <PartEditor
        className={cn("min-h-0 flex-1 lg:h-full lg:min-w-0", !desktop && tab !== "editor" && "hidden")}
        project={project}
        view={view}
        onView={setView}
        estimate={estimate}
        busy={state.busy}
        onRender={renderAgain}
        onAsk={ask}
        script={<ScriptView project={project} onRecord={record} />}
      />

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

// ---- the phone's tabs -----------------------------------------------------------------------

function PhoneTabs({ tab, onTab, working }: { tab: PhoneTab; onTab: (tab: PhoneTab) => void; working: boolean }) {
  const tabs: [PhoneTab, string, typeof Film][] = [
    ["chat", "Chat", MessageSquare],
    ["editor", "Editor", Film],
  ];
  return (
    <div role="tablist" aria-label="Chat or editor" className="grid shrink-0 grid-cols-2 gap-1 rounded-2xl bg-background p-1">
      {tabs.map(([id, label, Icon]) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={tab === id}
          onClick={() => onTab(id)}
          className={cn(
            "flex h-10 items-center justify-center gap-2 rounded-xl text-sm font-semibold transition-colors",
            tab === id ? "bg-panel-tile text-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Icon className="size-4" />
          {label}
          {id === "chat" && working ? <Loader2 className="size-3.5 animate-spin text-accent" /> : null}
        </button>
      ))}
    </div>
  );
}

// ---- the composer ---------------------------------------------------------------------------

function StudioComposer({
  inputRef,
  value,
  onChange,
  placeholder,
  locked,
  busy,
  ideas,
  onSend,
  spent,
  spentTitle,
  canUpload,
  onUpload,
  stop,
}: {
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  locked: boolean;
  busy: boolean;
  ideas: string[];
  onSend: (message: string) => Promise<boolean>;
  spent: string;
  spentTitle: string;
  canUpload: boolean;
  onUpload: () => void;
  stop?: () => void;
}) {
  const finePointer = useMediaQuery("(pointer: fine)");
  const [open, setOpen] = useState(false);
  const canSend = value.trim().length > 0 && !locked && !busy;

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value, inputRef]);

  const send = async () => {
    const message = value.trim();
    if (!message || !canSend) return;
    if (await onSend(message)) onChange("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Escape") setOpen(false);
    if (finePointer && e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="relative rounded-3xl bg-card p-2.5 transition-shadow focus-within:ring-2 focus-within:ring-accent/25">
      <AnimatePresence>
        {open && ideas.length ? (
          <motion.ul
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 6 }}
            transition={{ duration: 0.15, ease: EASE_OUT }}
            className="absolute inset-x-2 bottom-[calc(100%+0.5rem)] z-20 flex flex-col gap-0.5 rounded-2xl border border-border-strong bg-background p-1.5 shadow-2xl"
          >
            <li className="px-3 pb-1 pt-1.5 text-xs font-medium text-muted-foreground">Ideas</li>
            {ideas.map((idea) => (
              <li key={idea}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(idea);
                    setOpen(false);
                    inputRef.current?.focus();
                  }}
                  className="w-full rounded-xl px-3 py-2.5 text-left text-sm text-foreground transition-colors hover:bg-card"
                >
                  {idea}
                </button>
              </li>
            ))}
          </motion.ul>
        ) : null}
      </AnimatePresence>
      <textarea
        ref={inputRef}
        rows={2}
        value={value}
        disabled={locked}
        maxLength={2000}
        aria-label="Message"
        placeholder={placeholder}
        enterKeyHint={finePointer ? "send" : "enter"}
        onChange={(e) => {
          const next = e.target.value;
          if (next === "/" && ideas.length) {
            setOpen(true);
            return;
          }
          onChange(next);
        }}
        onKeyDown={onKeyDown}
        className="block max-h-40 min-h-[3.25rem] w-full resize-none bg-transparent px-2.5 py-1.5 text-base leading-snug text-foreground outline-none placeholder:text-muted-foreground/70 disabled:cursor-not-allowed lg:text-[15px]"
      />
      <div className="mt-1 flex items-center gap-1">
        <button
          type="button"
          title={canUpload ? "Upload one video of the whole part" : "Add a video once the part is written"}
          aria-label="Upload a video"
          disabled={!canUpload}
          onClick={onUpload}
          className="grid size-9 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-background hover:text-foreground disabled:opacity-35"
        >
          <Plus className="size-5" />
        </button>
        <button
          type="button"
          title="Ideas"
          aria-label="Ideas"
          aria-expanded={open}
          disabled={!ideas.length || locked}
          onClick={() => setOpen((o) => !o)}
          className={cn(
            "grid size-9 place-items-center rounded-xl transition-colors hover:bg-background hover:text-foreground disabled:opacity-35",
            open ? "text-foreground" : "text-muted-foreground",
          )}
        >
          <SquareSlash className="size-[18px]" />
        </button>
        <span title={spentTitle} className="ml-auto inline-flex items-center gap-1 pr-1.5 text-sm font-medium tabular-nums text-foreground/80">
          <Zap className="size-4 fill-warning text-warning" /> {spent}
        </span>
        {stop ? (
          <button
            type="button"
            onClick={stop}
            title="Stop"
            aria-label="Stop"
            className="grid size-10 place-items-center rounded-full bg-background text-foreground transition-colors hover:bg-panel-tile"
          >
            <Square className="size-3.5 fill-current" />
          </button>
        ) : (
          <button
            type="button"
            onClick={send}
            disabled={!canSend}
            title="Send"
            aria-label="Send"
            className="grid size-10 place-items-center rounded-full bg-foreground text-background transition-opacity disabled:opacity-25"
          >
            <ArrowUp className="size-5" />
          </button>
        )}
      </div>
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
      {`I'll make part ${project.chapter} as a teaser of about ${minutes} minute${minutes === 1 ? "" : "s"}: a hook on camera, the story in short beats over pictures, a poll and a call to action. `}
      {`Voice: ${labelFor("narration", part.narration)}. Pictures: ${labelFor("visual_style", part.visual_style)}. Language: ${labelFor("novel_language", part.language)}.\n\n`}
      {"Then it's your turn to record it from a teleprompter, line by line. I transcribe your narration, draw the characters and scenes, and render the reel.\n\n"}
      <span className="text-muted-foreground">
        {`Writing and checking take 2 to 4 minutes. Estimated ≈ ${usd(estimate.total_usd)} at Meta's list prices: writing ${usd(estimate.write_usd)}, about ${estimate.pictures} pictures ${usd(estimate.draw_usd)}, transcription ${transcribe}. Rendering is free.`}
      </span>
    </AssistantBubble>
  );
}

function StepGlyph({ state }: { state: FlowStep["state"] }) {
  if (state === "done") return <CircleCheck className="mt-0.5 size-5 shrink-0 text-success" />;
  if (state === "active") return <Loader2 className="mt-0.5 size-5 shrink-0 animate-spin text-foreground" />;
  if (state === "yours") return <Mic className="mt-0.5 size-5 shrink-0 text-warning" />;
  if (state === "failed") return <AlertCircle className="mt-0.5 size-5 shrink-0 text-danger" />;
  return <CircleDashed className="mt-0.5 size-5 shrink-0 text-muted-foreground/70" />;
}

function Checklist({
  project,
  steps,
  onRetry,
  busy,
}: {
  project: Project;
  steps: FlowStep[];
  onRetry: (step: FlowStep) => void;
  busy: boolean;
}) {
  const lines = thinking(project);
  return (
    <div className="rounded-2xl bg-card px-4 py-2">
      <ol className="flex flex-col">
        {steps.map((step) => (
          <li key={step.id} className="flex gap-3 py-2">
            <StepGlyph state={step.state} />
            <div className="min-w-0 flex-1">
              <p
                className={cn(
                  "text-[15px] leading-6",
                  step.state === "todo" ? "text-muted-foreground" : "text-foreground",
                  (step.state === "active" || step.state === "yours") && "font-medium",
                )}
              >
                {step.label}
              </p>
              {step.detail ? (
                <p className={cn("text-[13px] leading-snug", step.state === "failed" ? "text-danger" : "text-muted-foreground")}>
                  {step.detail}
                </p>
              ) : null}
              {step.state === "active" && lines.length ? (
                <div className="mt-1 flex flex-col gap-1">
                  {lines.map((line, i) => (
                    <p key={i} className="text-[13px] leading-snug text-muted-foreground/80 [overflow-wrap:anywhere]">
                      {line}
                    </p>
                  ))}
                </div>
              ) : null}
              {step.state === "failed" ? (
                <Button size="sm" className="mt-2" disabled={busy} onClick={() => onRetry(step)}>
                  <RotateCcw className="size-3.5" /> Try again
                </Button>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
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

function Card({ tone = "default", children }: { tone?: "default" | "warn"; children: ReactNode }) {
  return (
    <div className={cn("rounded-2xl p-4", tone === "warn" ? "bg-warning/10 ring-1 ring-warning/30" : "bg-card")}>
      {children}
    </div>
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
    <Card tone="warn">
      <p className="flex items-center gap-2 text-[15px] font-medium text-foreground">
        <Mic className="size-4 text-warning" /> Your turn: record the part
      </p>
      <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
        {rec.takes} short takes, each a line or two read from the teleprompter in one go.{" "}
        {rec.recorded ? `${rec.recorded} of ${rec.takes} done. ` : ""}
        After the last one, the reel is made on its own. Or upload one video of you reading the whole part.
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
    </Card>
  );
}

function ContinueCard({
  estimate,
  firstPass,
  busy,
  onContinue,
}: {
  estimate: PartEstimate;
  firstPass: boolean;
  busy: boolean;
  onContinue: () => void;
}) {
  const cost = firstPass ? `≈ ${usd(estimate.draw_usd + estimate.transcribe_usd)}` : "usually a few cents";
  return (
    <Card>
      <p className="text-sm text-foreground">
        {firstPass
          ? "Everything is recorded. Transcribe it, draw the pictures and render the reel?"
          : "Your recording changed. Transcribe it again, draw what changed and render a new reel?"}
      </p>
      <Button variant="primary" className="mt-3 h-11" disabled={busy} onClick={onContinue}>
        Make the reel · {cost}
      </Button>
    </Card>
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
  const lost = rec.video
    ? "your uploaded video no longer matches it"
    : rec.recorded
      ? `the ${rec.recorded} recorded take${rec.recorded > 1 ? "s are" : " is"} deleted`
      : "";
  return (
    <div className="flex flex-col gap-3">
      <UserBubble>{brief}</UserBubble>
      <Card>
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
      </Card>
    </div>
  );
}

function ReelReady({ project, estimate }: { project: Project; estimate: PartEstimate }) {
  const config = useConfig();
  const ttl = config.ttl_hours ?? 0;
  const last = project.renders[project.renders.length - 1];
  return (
    <div className="flex flex-col items-start gap-3">
      <AssistantBubble>
        {`Your reel is ready: ${seconds(last.duration)}, ${megabytes(last.size)}. `}
        {ttl ? `It's kept for ${ttl} hours (${expiresIn(project.updated_at, ttl)}), so download it. ` : ""}
        {`Spent ≈ ${usd(project.usage.estimated_usd)} (estimated ${usd(estimate.total_usd)}).`}
      </AssistantBubble>
      <a
        href={mediaUrl(project.id, last.key, true)}
        className="ml-1 inline-flex min-h-10 items-center gap-2 rounded-xl bg-foreground px-4 text-sm font-semibold text-background transition-opacity hover:opacity-90"
      >
        <Download className="size-4" /> Download the reel
      </a>
    </div>
  );
}

/** Keeps the newest message in view as the conversation grows, and when a phone's chat tab
 * is opened. */
function ScrollAnchor({ project, shown }: { project: Project; shown: boolean }) {
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
    if (!shown) first.current = true; // a hidden list forgets where it was: jump, don't glide
    if (!shown || !el || !list || list.scrollHeight <= list.clientHeight) return;
    list.scrollTo({ top: list.scrollHeight, behavior: first.current || reduce ? "auto" : "smooth" });
    first.current = false;
  }, [key, reduce, shown]);
  // The list may only get its height after the first paint (the frame turns bare, a tab
  // opens): jump to the end then.
  useEffect(() => {
    const list = ref.current?.closest(".overflow-y-auto");
    if (!list || !shown) return;
    const observer = new ResizeObserver(() => {
      if (!first.current || list.scrollHeight <= list.clientHeight) return;
      list.scrollTo({ top: list.scrollHeight });
      first.current = false;
    });
    observer.observe(list);
    return () => observer.disconnect();
  }, [shown]);
  return <div ref={ref} />;
}
