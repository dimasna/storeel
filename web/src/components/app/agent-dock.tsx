import { createContext, useContext, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { AnimatePresence, motion, useDragControls, useReducedMotion } from "motion/react";
import { AlertCircle, ArrowUp, Check, Clock, Feather, Loader2, RotateCcw, X } from "lucide-react";
import { api } from "@/lib/api";
import type { AgentAction, AgentMessage, Project } from "@/lib/types";
import { jobActive } from "@/lib/use-project";
import { useMediaQuery } from "@/lib/use-media-query";
import { SPRING_PANEL } from "@/lib/ease";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ProgressBar } from "@/components/ui/primitives";
import type { UseProjectState } from "./project-view";

// The editing agent's chat. Phones first: a bottom sheet over the page that you swipe down to
// close. From the `lg` breakpoint it is a floating card, and the page stays usable beside it.
// The pieces (messages, proposals, activity, composer) are shared with the part studio, which
// shows the same conversation inline.

export function agentSuggestions(project: Project): string[] {
  const out: string[] = [];
  if (project.path === "novel" && project.part_pictures)
    out.push("Show each character when they're talked about");
  if (project.source && project.style.background === "dalang")
    out.push("Cut me out and put the pictures behind me");
  if (Object.values(project.caption_notes || {}).some((n) => n.script))
    out.push("Use the script's words where the captions differ");
  if (project.analysis?.moments.length) out.push("Hide the pictures in the first 5 seconds");
  const character = Object.values(project.part_pictures || {}).find((p) => p.kind === "character" && p.key);
  if (character) {
    const name = character.id.replace(/_/g, " ");
    out.push(`Dress ${name.charAt(0).toUpperCase()}${name.slice(1)} in dark red`);
  }
  out.push(
    project.style.captions === "bold" || project.style.captions === "serif"
      ? "Make the captions yellow and uppercase"
      : "Bold captions that come in word by word",
  );
  if (project.analysis?.moments.length) out.push("Draw the first picture again as a cut-out");
  out.push("Render it under 25 MB");
  return out.slice(0, 4);
}

function cost(value: number): string {
  return value > 0 ? `≈ $${value.toFixed(2)}` : "no API cost";
}

/** The pending proposals of the agent's latest reply. */
function usePending(project: Project): AgentAction[] {
  const messages = project.agent?.messages ?? [];
  const lastReply = [...messages].reverse().find((m) => m.role === "assistant");
  return useMemo(() => (lastReply?.actions ?? []).filter((a) => a.status === "pending"), [lastReply]);
}

export function AgentDock({ project, state }: { project: Project; state: UseProjectState }) {
  const [open, setOpen] = useState(false);
  const desktop = useMediaQuery("(min-width: 1024px)");
  const reduce = useReducedMotion();
  const drag = useDragControls();
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const messages: AgentMessage[] = project.agent?.messages ?? [];
  const job = project.job;
  const active = jobActive(project);
  const thinking = active && job?.kind === "agent";
  const applying = active && job?.kind === "agent_apply";
  const pending = usePending(project);
  const attention = pending.length > 0 || thinking || applying;

  // Keep the newest message in view.
  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTo({ top: list.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  }, [open, messages.length, thinking, applying, pending.length, job?.step, reduce]);

  // The sheet covers the page on a phone: don't let the page scroll behind it.
  useEffect(() => {
    if (!open || desktop) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open, desktop]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    if (desktop) inputRef.current?.focus(); // on a phone this would pop the keyboard up at once
    return () => document.removeEventListener("keydown", onKey);
  }, [open, desktop]);

  const sheet = desktop
    ? { initial: { opacity: 0, y: 16, scale: 0.98 }, animate: { opacity: 1, y: 0, scale: 1 }, exit: { opacity: 0, y: 16, scale: 0.98 } }
    : { initial: { y: "100%" }, animate: { y: 0 }, exit: { y: "100%" } };

  return (
    <>
      <AnimatePresence>
        {!open && (
          <motion.button
            key="fab"
            type="button"
            onClick={() => setOpen(true)}
            aria-label="Open the editor"
            initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.85 }}
            animate={reduce ? { opacity: 1 } : { opacity: 1, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.85 }}
            whileTap={reduce ? undefined : { scale: 0.95 }}
            transition={SPRING_PANEL}
            className="fixed bottom-[calc(env(safe-area-inset-bottom)+1rem)] right-4 z-[45] flex h-13 items-center gap-2.5 rounded-full border border-[#1f1a15]/10 bg-primary pl-3 pr-5 text-sm font-semibold text-primary-foreground shadow-[0_16px_36px_-14px_rgb(120_60_10/0.6)] lg:bottom-6 lg:right-6"
          >
            <span className="grid size-8 place-items-center rounded-full bg-[#1f1a15] text-primary">
              <Feather className="size-4" />
            </span>
            Ask Storeel
            {attention ? (
              <span className="absolute -right-0.5 -top-0.5 size-3.5 rounded-full border-2 border-background bg-accent" />
            ) : null}
          </motion.button>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {open && !desktop && (
          <motion.div
            key="backdrop"
            className="fixed inset-0 z-[44] bg-black/50"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setOpen(false)}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {open && (
          <motion.section
            key={desktop ? "card" : "sheet"}
            role="dialog"
            aria-label="Editor"
            aria-modal={!desktop}
            {...(reduce ? { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 } } : sheet)}
            transition={SPRING_PANEL}
            drag={desktop ? false : "y"}
            dragListener={false}
            dragControls={drag}
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.6 }}
            onDragEnd={(_, info) => {
              if (info.offset.y > 110 || info.velocity.y > 600) setOpen(false);
            }}
            className={cn(
              "fixed inset-x-0 bottom-0 z-[45] flex h-[min(88dvh,46rem)] flex-col rounded-t-3xl border border-border-strong bg-background/95 shadow-2xl backdrop-blur-xl",
              "lg:inset-x-auto lg:bottom-6 lg:right-6 lg:h-[min(40rem,calc(100dvh-7rem))] lg:w-[25rem] lg:rounded-3xl",
            )}
          >
            <header
              onPointerDown={(e) => !desktop && drag.start(e)}
              className="shrink-0 cursor-grab touch-none select-none active:cursor-grabbing lg:cursor-default"
            >
              <div className="mx-auto mt-2.5 h-1.5 w-10 rounded-full bg-border-strong lg:hidden" />
              <div className="flex items-center gap-3 px-4 pb-3 pt-2 lg:pt-4">
                <span className="grid size-9 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground">
                  <Feather className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="font-display text-xl leading-none text-foreground">Ask Storeel</h2>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    Captions, pictures and style, in your words. New pictures and renders wait for your OK.
                  </p>
                </div>
                {messages.length > 0 ? (
                  <HeaderButton
                    label="New chat"
                    disabled={active}
                    onClick={() => {
                      if (confirm("Start a new chat? The conversation is cleared; your edits stay."))
                        state.act(() => api.agentClear(project.id));
                    }}
                  >
                    <RotateCcw className="size-4" />
                  </HeaderButton>
                ) : null}
                <HeaderButton label="Close" onClick={() => setOpen(false)}>
                  <X className="size-5" />
                </HeaderButton>
              </div>
            </header>

            <div ref={listRef} className="flex-1 overflow-y-auto overscroll-contain border-t border-border px-4 py-4">
              {messages.length === 0 ? (
                <AgentSuggestions project={project} state={state} intro="Tell me what to change, in your own words. For example:" />
              ) : (
                <AgentThread messages={messages} applying={applying} />
              )}
              <PendingActions project={project} state={state} />
              <AgentActivity project={project} state={state} />
            </div>

            <div className="shrink-0 border-t border-border px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3">
              <AgentComposer project={project} state={state} inputRef={inputRef} />
            </div>
          </motion.section>
        )}
      </AnimatePresence>
    </>
  );
}

/** Example requests, sent with one tap. */
export function AgentSuggestions({
  project,
  state,
  intro,
}: {
  project: Project;
  state: UseProjectState;
  intro: string;
}) {
  const active = jobActive(project);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">{intro}</p>
      <div className="flex flex-col gap-2">
        {agentSuggestions(project).map((s) => (
          <button
            key={s}
            type="button"
            disabled={active || state.busy}
            onClick={() => state.act(() => api.agentSend(project.id, s))}
            className="min-h-11 rounded-2xl border border-border-strong bg-card px-4 py-2.5 text-left text-sm text-foreground transition-colors hover:border-accent/60 disabled:opacity-50"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

/** The conversation: the user's requests and the agent's replies with what each one did. */
export function AgentThread({ messages, applying }: { messages: AgentMessage[]; applying: boolean }) {
  return (
    <ol className="flex flex-col gap-4">
      {messages.map((m, i) => (
        <li key={`${i}-${m.created_at}`}>
          <ChatMessage message={m} applying={applying} />
        </li>
      ))}
    </ol>
  );
}

/** The changes waiting for the user's OK, each with its cost; the rest are dismissed. */
export function PendingActions({ project, state }: { project: Project; state: UseProjectState }) {
  const pending = usePending(project);
  const pendingKey = pending.map((a) => a.id).join(",");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  useEffect(() => setSelected(new Set(pending.map((a) => a.id))), [pendingKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!pending.length || jobActive(project)) return null;
  const selectedCost = pending.filter((a) => selected.has(a.id)).reduce((n, a) => n + a.cost_usd, 0);
  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="mt-3 rounded-2xl border border-accent/40 bg-accent/5 p-3">
      <p className="mb-1 px-1 text-xs font-semibold text-foreground">Waiting for your OK</p>
      <ul className="flex flex-col">
        {pending.map((a) => (
          <li key={a.id}>
            <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-xl px-1 py-1.5">
              <input
                type="checkbox"
                checked={selected.has(a.id)}
                onChange={() => toggle(a.id)}
                className="size-5 shrink-0 accent-accent"
              />
              <span className="flex-1 text-sm leading-snug text-foreground">{a.summary}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{cost(a.cost_usd)}</span>
            </label>
          </li>
        ))}
      </ul>
      <div className="mt-2 flex gap-2">
        <Button
          variant="primary"
          className="h-11 flex-1"
          disabled={selected.size === 0 || state.busy}
          onClick={() => state.act(() => api.agentDecide(project.id, [...selected]))}
        >
          Run {selected.size}
          {selectedCost > 0 ? ` · ≈ $${selectedCost.toFixed(2)}` : ""}
        </Button>
        <Button
          variant="ghost"
          className="h-11"
          disabled={state.busy}
          onClick={() => state.act(() => api.agentDecide(project.id, []))}
        >
          Dismiss
        </Button>
      </div>
      <p className="mt-2 px-1 text-xs text-muted-foreground">Or type below to change the plan.</p>
    </div>
  );
}

/** The agent thinking, or the approved changes running, with a way to stop it. */
export function AgentActivity({ project, state }: { project: Project; state: UseProjectState }) {
  const job = project.job;
  const active = jobActive(project);
  if (!job || !active) return null;
  if (job.kind === "agent")
    return (
      <div className="mt-4 flex items-center gap-2">
        <div className="flex items-center gap-2 rounded-2xl rounded-bl-md border border-border bg-card px-3.5 py-2.5 text-sm text-muted-foreground">
          <Dots />
          {job.cancel_requested ? "Stopping" : job.step || "Thinking"}…
        </div>
        {!job.cancel_requested ? (
          <button
            type="button"
            onClick={() => state.act(() => api.cancelJob(job.id))}
            className="min-h-11 px-2 text-xs font-semibold text-muted-foreground hover:text-foreground"
          >
            Stop
          </button>
        ) : null}
      </div>
    );
  if (job.kind === "agent_apply")
    return (
      <div className="mt-4 rounded-2xl border border-border bg-card p-3">
        <div className="mb-2 flex items-center gap-2 text-sm text-foreground">
          <Loader2 className="size-4 animate-spin text-accent" />
          <span className="flex-1 truncate">{job.step || "Running the approved changes"}</span>
          <span className="text-xs text-muted-foreground">{Math.round((job.progress || 0) * 100)}%</span>
        </div>
        <ProgressBar value={job.progress || 0} />
      </div>
    );
  return null;
}

/**
 * The message box. By default it sends to the editing agent; `onSend` takes the message
 * instead (the part studio uses it before the reel exists).
 */
export function AgentComposer({
  project,
  state,
  inputRef,
  placeholder = "Ask for a change…",
  disabledNote,
  onSend,
  sendLabel,
}: {
  project: Project;
  state: UseProjectState;
  inputRef?: React.RefObject<HTMLTextAreaElement | null>;
  placeholder?: string;
  disabledNote?: ReactNode;
  onSend?: (message: string) => Promise<boolean>;
  sendLabel?: ReactNode;
}) {
  const [draft, setDraft] = useState("");
  const finePointer = useMediaQuery("(pointer: fine)");
  const ownRef = useRef<HTMLTextAreaElement>(null);
  const ref = inputRef ?? ownRef;
  const active = jobActive(project);
  const kind = project.job?.kind;
  const otherJob = active && kind !== "agent" && kind !== "agent_apply";
  const blocked = Boolean(disabledNote) || active;
  const canSend = draft.trim().length > 0 && !blocked && !state.busy;

  const resize = (el: HTMLTextAreaElement) => {
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
  };

  const send = async () => {
    const message = draft.trim();
    if (!message || blocked) return;
    const sent = onSend
      ? await onSend(message)
      : Boolean(await state.act(() => api.agentSend(project.id, message)));
    if (sent) {
      setDraft("");
      if (ref.current) ref.current.style.height = "auto";
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (canSend) send();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // With a keyboard and mouse, Enter sends and Shift+Enter is a new line. On touch screens
    // Enter is a new line and the button sends.
    if (finePointer && e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (canSend) send();
    }
  };

  return (
    <form onSubmit={onSubmit}>
      {disabledNote ? (
        <p className="mb-2 px-1 text-xs text-muted-foreground">{disabledNote}</p>
      ) : otherJob ? (
        <p className="mb-2 px-1 text-xs text-muted-foreground">Wait for the current job to finish.</p>
      ) : null}
      <div className="flex items-end gap-2">
        <textarea
          ref={ref}
          rows={1}
          value={draft}
          maxLength={2000}
          enterKeyHint={finePointer ? "send" : "enter"}
          placeholder={placeholder}
          aria-label="Message"
          disabled={Boolean(disabledNote)}
          onChange={(e) => {
            setDraft(e.target.value);
            resize(e.target);
          }}
          onKeyDown={onKeyDown}
          className="max-h-32 min-h-11 flex-1 resize-none rounded-2xl border border-input bg-card px-4 py-2.5 text-base leading-snug text-foreground placeholder:text-muted-foreground/70 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30 disabled:opacity-60 lg:text-sm"
        />
        <button
          type="submit"
          aria-label="Send"
          disabled={!canSend}
          className={cn(
            "flex h-11 shrink-0 items-center justify-center gap-1.5 rounded-full bg-primary text-sm font-semibold text-primary-foreground transition-opacity disabled:opacity-40",
            sendLabel ? "px-4" : "w-11",
          )}
        >
          {sendLabel ?? null}
          <ArrowUp className="size-5" />
        </button>
      </div>
    </form>
  );
}

function HeaderButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onPointerDown={(e) => e.stopPropagation()} // a tap here is a click, not the start of a swipe
      onClick={onClick}
      className="grid size-11 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-card hover:text-foreground disabled:opacity-40"
    >
      {children}
    </button>
  );
}

export function ChatMessage({ message, applying }: { message: AgentMessage; applying: boolean }) {
  if (message.role === "user") return <UserBubble>{message.text}</UserBubble>;
  const shown = message.actions.filter((a) => a.status !== "pending");
  return (
    <div className="flex flex-col items-start gap-2">
      <AssistantBubble>{message.text}</AssistantBubble>
      {shown.length ? (
        <ul className="flex w-full flex-col gap-1 pl-1">
          {shown.map((a) => (
            <ActionLine key={a.id} action={a} applying={applying} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function UserBubble({ children }: { children: ReactNode }) {
  const plain = useContext(ChatLook) === "plain";
  return (
    <div className="flex justify-end">
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md px-3.5 py-2 text-[15px] leading-snug lg:text-sm",
          plain ? "bg-panel-tile text-foreground" : "bg-primary text-primary-foreground",
        )}
      >
        {children}
      </div>
    </div>
  );
}

export function AssistantBubble({ children, className }: { children: ReactNode; className?: string }) {
  const plain = useContext(ChatLook) === "plain";
  return (
    <div
      className={cn(
        "whitespace-pre-wrap break-words text-[15px] leading-relaxed text-foreground lg:text-sm",
        plain ? "px-1" : "max-w-[92%] rounded-2xl rounded-bl-md border border-border bg-card px-3.5 py-2 leading-snug",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** How the chat draws messages: in bubbles (the editor's sheet) or as plain text beside a
 * neutral bubble for the user (the part studio's chat panel). */
export const ChatLook = createContext<"bubbles" | "plain">("bubbles");

function ActionLine({ action, applying }: { action: AgentAction; applying: boolean }) {
  const icon =
    action.status === "done" ? (
      <Check className="size-3.5 text-success" />
    ) : action.status === "failed" ? (
      <AlertCircle className="size-3.5 text-danger" />
    ) : action.status === "approved" ? (
      applying ? <Loader2 className="size-3.5 animate-spin text-accent" /> : <Clock className="size-3.5" />
    ) : (
      <X className="size-3.5" />
    );
  return (
    <li className="flex items-start gap-2 text-xs leading-snug text-muted-foreground">
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span className={cn(action.status === "dismissed" && "line-through opacity-70")}>
        {action.summary}
        {action.status === "failed" && action.error ? `: ${action.error}` : ""}
      </span>
    </li>
  );
}

export function Dots() {
  return (
    <span className="flex items-center gap-1" aria-hidden>
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="size-1.5 rounded-full bg-muted-foreground motion-safe:animate-bounce"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </span>
  );
}
