import { useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";
import { BookText, Check, ChevronDown, FileUp, Languages, Loader2, Mic, Palette, Sparkles } from "lucide-react";
import { api, ApiError, apiKey } from "@/lib/api";
import type { Novel, NovelSummary, PartEstimate } from "@/lib/types";
import { useConfig } from "@/lib/config";
import { enumOf, labelFor } from "@/lib/labels";
import { lookPicture } from "@/lib/gallery";
import { useToast } from "@/lib/toast";
import { navigate } from "@/lib/router";
import { requestKey } from "@/App";
import { cn } from "@/lib/utils";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/primitives";

// The home page's card, after OpusClip's: two large tiles (the chapter, and an optional look),
// a row of chips (the voice and the language) and a send button. Send makes the novel, the
// chapter and its part, and starts writing it; the part's page takes over from there.

const DRAFT = "storeel.chapterDraft";
const MIN_CHARS = 200;
// Short names for the chips (the novel page's form shows the long ones).
const VOICE_CHIP: Record<string, string> = {
  casual: "Casual voice",
  warm: "Warm voice",
  dramatic: "Dramatic narrator",
  funny: "Funny gossip",
};

/** Indonesian or English, from the most common short words of the text. */
function guessLanguage(text: string): "id" | "en" {
  const sample = ` ${text.slice(0, 5000).toLowerCase()} `;
  const count = (re: RegExp) => (sample.match(re) || []).length;
  const id = count(/\s(yang|dan|tidak|itu|dengan|aku|kamu|ini|saya|dia|akan|sudah|tapi|apa|di|ke|dari)\s/g);
  const en = count(/\s(the|and|not|that|with|you|this|is|was|to|of|for|he|she|but|what|it)\s/g);
  return en > id ? "en" : "id";
}

function ChipSelect({
  icon: Icon,
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <label
      title={label}
      className={cn(
        "relative inline-flex h-10 min-w-0 items-center gap-2 rounded-xl bg-panel-tile pl-3 pr-8 text-sm font-medium text-foreground transition-colors focus-within:ring-2 focus-within:ring-accent/40 max-sm:w-full",
        disabled ? "opacity-70" : "hover:brightness-110",
      )}
    >
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      <span className="sr-only">{label}</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-0 flex-1 cursor-pointer appearance-none truncate bg-transparent outline-none disabled:cursor-default"
      >
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 size-4 text-muted-foreground" />
    </label>
  );
}

/** One of the card's two large tiles. */
function Tile({
  icon: Icon,
  title,
  subtitle,
  onClick,
  done,
  picture,
  highlight,
}: {
  icon: ComponentType<{ className?: string }>;
  title: ReactNode;
  subtitle: ReactNode;
  onClick: () => void;
  done?: boolean;
  picture?: string;
  highlight?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group relative flex min-h-[7.5rem] flex-col items-center justify-center gap-1 overflow-hidden rounded-2xl bg-panel-tile px-4 py-5 text-center transition-[filter,box-shadow] hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
        highlight && "ring-2 ring-accent/70",
      )}
    >
      {picture ? (
        <>
          <img src={picture} alt="" className="absolute inset-0 size-full object-cover object-[50%_28%] opacity-60 transition-transform duration-500 group-hover:scale-105" />
          <span className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/45 to-black/20" />
        </>
      ) : null}
      <span className={cn("relative mb-1 grid size-7 place-items-center rounded-lg", done ? "bg-success/20 text-success" : picture ? "text-white" : "text-foreground")}>
        {done ? <Check className="size-4" /> : <Icon className="size-5" />}
      </span>
      <span className={cn("relative text-base font-medium", picture ? "text-white" : "text-foreground")}>{title}</span>
      <span className={cn("relative text-xs leading-snug", picture ? "text-white/80" : "text-muted-foreground")}>{subtitle}</span>
    </button>
  );
}

export function ChapterComposer({
  look,
  onLook,
  highlightLook,
}: {
  look: string | null;
  onLook: (look: string) => void;
  highlightLook?: boolean;
}) {
  const config = useConfig();
  const { toast } = useToast();
  const [novels, setNovels] = useState<NovelSummary[]>([]);
  const [target, setTarget] = useState("new"); // "new", or the id of one of the user's novels
  const [novel, setNovel] = useState<Novel | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState(() => sessionStorage.getItem(DRAFT) || "");
  const [brief, setBrief] = useState("");
  const [voice, setVoice] = useState("casual");
  const [language, setLanguage] = useState<string>("auto");
  const [estimate, setEstimate] = useState<PartEstimate | null>(null);
  const [sending, setSending] = useState(false);
  const [pasting, setPasting] = useState(false);
  const [picking, setPicking] = useState(false);

  const chars = text.trim().length;
  const lang = language === "auto" ? guessLanguage(text) : language;
  const ready = chars >= MIN_CHARS && (target !== "new" || Boolean(title.trim()));
  const chosenLook = novel ? novel.visual_style : look;

  useEffect(() => {
    api
      .listNovels()
      .then((all) => setNovels(all.filter((n) => !n.read_only)))
      .catch(() => setNovels([]));
  }, []);

  useEffect(() => {
    if (target === "new") return setNovel(null);
    let stale = false;
    api
      .getNovel(target)
      .then((n) => !stale && setNovel(n))
      .catch(() => !stale && setTarget("new"));
    return () => {
      stale = true;
    };
  }, [target]);

  // Keep the pasted chapter if the page reloads before it is sent.
  useEffect(() => {
    const timer = window.setTimeout(() => sessionStorage.setItem(DRAFT, text), 300);
    return () => window.clearTimeout(timer);
  }, [text]);

  useEffect(() => {
    let stale = false;
    const timer = window.setTimeout(() => {
      api
        .estimatePart(Math.max(chars, MIN_CHARS))
        .then((e) => !stale && setEstimate(e))
        .catch(() => {});
    }, 350);
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
  }, [chars]);

  const options = (field: string, kind = field): [string, string][] =>
    enumOf(config.novel, field).map((v) => [v, labelFor(kind, v)]);

  const send = async () => {
    if (sending) return;
    if (!ready) {
      setPasting(true);
      return;
    }
    if (!apiKey.get()) {
      requestKey("Add your Muse / Model API key. It writes, draws and transcribes the part; it stays in this browser.");
      return;
    }
    setSending(true);
    let partId: string | null = null;
    try {
      let novelId = target;
      if (target === "new") {
        const made = await api.createNovel({
          title: title.trim(),
          language: lang,
          narration: voice,
          visual_style: look ?? "realistic_3d",
          watermark: "",
        });
        novelId = made.id;
        setTarget(made.id); // a retry adds the chapter to this novel instead of making another
      }
      const updated = await api.addChapter(novelId, { text: text.trim(), title: "", number: null });
      const number = Math.max(...updated.chapters.map((c) => c.number));
      const part = await api.openChapterReel(novelId, number);
      partId = part.id;
      await api.writePart(part.id, false, brief.trim() || undefined);
      sessionStorage.removeItem(DRAFT);
      navigate(`/p/${part.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.code === "api_key_required") requestKey("Add your Muse / Model API key to continue.");
      else toast(e instanceof Error ? e.message : String(e), "error");
      if (partId) {
        sessionStorage.removeItem(DRAFT);
        navigate(`/p/${partId}`); // the part exists: it can be started from its page
      }
    } finally {
      setSending(false);
    }
  };

  const chapterTitle = ready
    ? novel
      ? `${novel.title}, part ${novel.next_chapter}`
      : title.trim()
    : chars >= MIN_CHARS
      ? "Add the novel's title"
      : "Paste a chapter";
  const chapterSub = ready
    ? `${chars.toLocaleString()} characters · ${labelFor("novel_language", novel ? novel.language : lang)} · tap to edit`
    : chars >= MIN_CHARS
      ? `${chars.toLocaleString()} characters pasted · tap to finish`
      : "Of a new novel, or the next part of yours";
  const cost = estimate && chars >= MIN_CHARS ? `≈ $${estimate.total_usd.toFixed(2)}` : "";

  return (
    <div className="rounded-[28px] bg-card p-3 shadow-2xl shadow-black/10 sm:p-3.5">
      <div className="grid gap-3 sm:grid-cols-2">
        <Tile icon={BookText} title={chapterTitle} subtitle={chapterSub} done={ready} onClick={() => setPasting(true)} />
        <Tile
          icon={Palette}
          title={chosenLook ? `Look: ${labelFor("visual_style", chosenLook)}` : "(Optional) Pick a look"}
          subtitle={
            novel ? "Every part of a novel keeps its look" : chosenLook ? "Tap to change" : "Show Storeel the picture style you'd like"
          }
          picture={chosenLook ? lookPicture(chosenLook) : undefined}
          highlight={highlightLook}
          onClick={() => (novel ? toast("This novel's parts all keep its look.", "info") : setPicking(true))}
        />
      </div>

      <div className="mt-3 grid grid-cols-2 items-center gap-2 sm:flex sm:flex-wrap">
        <ChipSelect
          icon={Mic}
          label="Voice"
          value={novel ? novel.narration : voice}
          disabled={Boolean(novel)}
          options={enumOf(config.novel, "narration").map((v): [string, string] => [v, VOICE_CHIP[v] ?? labelFor("narration", v)])}
          onChange={setVoice}
        />
        <ChipSelect
          icon={Languages}
          label="Language"
          value={novel ? novel.language : language}
          disabled={Boolean(novel)}
          options={[
            ["auto", chars >= MIN_CHARS ? `${labelFor("novel_language", lang)} (auto)` : "Detect language"],
            ...options("language", "novel_language"),
          ]}
          onChange={setLanguage}
        />
        <div className="hidden flex-1 items-center justify-end gap-3 sm:flex">
          {cost ? <span className="text-xs text-muted-foreground">{cost}</span> : null}
          <button
            type="button"
            onClick={send}
            disabled={sending}
            aria-label="Send"
            title={ready ? "Send: write the part" : "Paste a chapter first"}
            className={cn(
              "grid size-10 place-items-center rounded-xl transition-[opacity,filter]",
              ready ? "text-white hover:brightness-110" : "bg-panel-tile text-muted-foreground",
            )}
            style={ready ? { background: "var(--gradient-accent)" } : undefined}
          >
            {sending ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
          </button>
        </div>
      </div>
      {/* Phones: one wide button, as on OpusClip. */}
      <button
        type="button"
        onClick={send}
        disabled={sending}
        className={cn(
          "mt-3 flex h-12 w-full items-center justify-center gap-2 rounded-xl text-base font-semibold transition-[opacity,filter] sm:hidden",
          ready ? "text-white" : "bg-panel-tile text-muted-foreground",
        )}
        style={ready ? { background: "var(--gradient-accent)" } : undefined}
      >
        {sending ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
        {sending
          ? "Starting…"
          : ready
            ? `Send & write the part${cost ? ` · ${cost}` : ""}`
            : chars >= MIN_CHARS
              ? "Add the novel's title first"
              : "Paste a chapter first"}
      </button>

      <PasteDialog
        open={pasting}
        onClose={() => setPasting(false)}
        novels={novels}
        target={target}
        setTarget={setTarget}
        novel={novel}
        title={title}
        setTitle={setTitle}
        text={text}
        setText={setText}
        brief={brief}
        setBrief={setBrief}
      />
      <LookDialog
        open={picking}
        onClose={() => setPicking(false)}
        value={look}
        onPick={(v) => {
          onLook(v);
          setPicking(false);
        }}
      />
    </div>
  );
}

function PasteDialog({
  open,
  onClose,
  novels,
  target,
  setTarget,
  novel,
  title,
  setTitle,
  text,
  setText,
  brief,
  setBrief,
}: {
  open: boolean;
  onClose: () => void;
  novels: NovelSummary[];
  target: string;
  setTarget: (v: string) => void;
  novel: Novel | null;
  title: string;
  setTitle: (v: string) => void;
  text: string;
  setText: (v: string) => void;
  brief: string;
  setBrief: (v: string) => void;
}) {
  const { toast } = useToast();
  const file = useRef<HTMLInputElement>(null);
  const chars = text.trim().length;

  const done = () => {
    if (chars < MIN_CHARS) return toast("Paste the whole chapter: at least a few paragraphs.", "error");
    if (target === "new" && !title.trim()) return toast("Give the novel a title: the reel's call to action names it.", "error");
    onClose();
  };

  return (
    <Modal open={open} onClose={onClose} title="Paste a chapter" className="max-w-2xl">
      <div className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Novel">
            <Select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="new">New novel</option>
              {novels.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.title}
                </option>
              ))}
            </Select>
          </Field>
          {target === "new" ? (
            <Field label="Novel title">
              <Input value={title} maxLength={120} placeholder="The Light at Gull Point" onChange={(e) => setTitle(e.target.value)} />
            </Field>
          ) : (
            <Field label="This chapter becomes">
              <p className="flex h-[38px] items-center text-sm text-foreground">
                {novel ? `Part ${novel.next_chapter}` : "…"}
              </p>
            </Field>
          )}
        </div>
        <Field
          label={
            <span className="flex items-center justify-between gap-2">
              <span>Chapter text</span>
              <button
                type="button"
                onClick={() => file.current?.click()}
                className="inline-flex items-center gap-1 font-semibold text-accent hover:underline"
              >
                <FileUp className="size-3.5" /> Load a .txt file
              </button>
            </span>
          }
          hint={chars ? `${chars.toLocaleString()} characters` : "The whole chapter: the part is written from it."}
        >
          <Textarea
            rows={12}
            autoFocus
            maxLength={200000}
            value={text}
            placeholder="Paste the chapter here…"
            onChange={(e) => setText(e.target.value)}
            className="max-h-[50dvh] text-base sm:text-sm"
          />
        </Field>
        <Field label="What should this part focus on? (optional)">
          <Input
            value={brief}
            maxLength={600}
            placeholder="e.g. end on the bell ringing with no one at the door"
            onChange={(e) => setBrief(e.target.value)}
          />
        </Field>
        <div className="flex justify-end">
          <Button variant="primary" className="h-11 px-6" onClick={done}>
            Done
          </Button>
        </div>
      </div>
      <input
        ref={file}
        type="file"
        accept=".txt,.md,text/plain,text/markdown"
        hidden
        onChange={async (e) => {
          const picked = e.target.files?.[0];
          e.target.value = "";
          if (!picked) return;
          if (picked.size > 400_000) return toast("That file is too large for one chapter.", "error");
          setText(await picked.text());
        }}
      />
    </Modal>
  );
}

function LookDialog({
  open,
  onClose,
  value,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  value: string | null;
  onPick: (look: string) => void;
}) {
  const config = useConfig();
  const looks = enumOf(config.novel, "visual_style");
  return (
    <Modal open={open} onClose={onClose} title="Pick a look" className="max-w-2xl">
      <p className="-mt-2 mb-4 text-sm text-muted-foreground">
        How Muse Image draws the characters and scenes of every part of this novel.
      </p>
      <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-4">
        {looks.map((look) => {
          const picture = lookPicture(look);
          return (
            <button
              key={look}
              type="button"
              onClick={() => onPick(look)}
              className={cn(
                "group relative aspect-[3/4] overflow-hidden rounded-xl bg-panel-tile text-left transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                value === look && "ring-2 ring-accent",
              )}
            >
              {picture ? (
                <img src={picture} alt="" className="absolute inset-0 size-full object-cover transition-transform duration-300 group-hover:scale-105" />
              ) : null}
              <span className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/10 to-transparent" />
              <span className="absolute inset-x-2 bottom-2 text-xs font-semibold leading-tight text-white">
                {labelFor("visual_style", look)}
              </span>
              {value === look ? (
                <span className="absolute right-2 top-2 grid size-6 place-items-center rounded-full bg-accent text-accent-foreground">
                  <Check className="size-3.5" />
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </Modal>
  );
}
