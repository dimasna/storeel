import { useEffect, useRef, useState, type ComponentType } from "react";
import { ArrowUp, BookText, ChevronDown, Languages, Loader2, Mic, Palette, Sparkles } from "lucide-react";
import { api, ApiError, apiKey } from "@/lib/api";
import type { Novel, NovelSummary, PartEstimate } from "@/lib/types";
import { useConfig } from "@/lib/config";
import { enumOf, labelFor } from "@/lib/labels";
import { useToast } from "@/lib/toast";
import { navigate } from "@/lib/router";
import { requestKey } from "@/App";
import { cn } from "@/lib/utils";

// The home page's input card: paste a chapter (of a new novel, or the next one of yours), pick
// the look and the voice, optionally say what the part should focus on, and send. Send makes
// the novel, the chapter and its part, and starts writing it; the part's page takes over.

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
  className,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <label
      className={cn(
        "relative inline-flex h-9 min-w-0 items-center gap-1.5 rounded-full border border-border-strong bg-background pl-3 pr-7 text-xs font-semibold text-foreground transition-colors hover:border-accent/60 focus-within:border-accent",
        className,
      )}
      title={label}
    >
      <Icon className="size-3.5 shrink-0 text-accent" />
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="min-w-0 cursor-pointer appearance-none truncate bg-transparent outline-none"
      >
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 size-3.5 text-muted-foreground" />
    </label>
  );
}

export function ChapterComposer() {
  const config = useConfig();
  const { toast } = useToast();
  const [novels, setNovels] = useState<NovelSummary[]>([]);
  const [target, setTarget] = useState("new"); // "new", or the id of one of the user's novels
  const [novel, setNovel] = useState<Novel | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState(() => sessionStorage.getItem(DRAFT) || "");
  const [brief, setBrief] = useState("");
  const [look, setLook] = useState("realistic_3d");
  const [voice, setVoice] = useState("casual");
  const [language, setLanguage] = useState<string>("auto");
  const [estimate, setEstimate] = useState<PartEstimate | null>(null);
  const [sending, setSending] = useState(false);
  const titleRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const chars = text.trim().length;
  const lang = language === "auto" ? guessLanguage(text) : language;

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
    const chapter = text.trim();
    if (chapter.length < MIN_CHARS) {
      toast("Paste the whole chapter: at least a few paragraphs.", "error");
      textRef.current?.focus();
      return;
    }
    if (target === "new" && !title.trim()) {
      toast("Give the novel a title: the reel's call to action names it.", "error");
      titleRef.current?.focus();
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
          visual_style: look,
          watermark: "",
        });
        novelId = made.id;
        setTarget(made.id); // a retry adds the chapter to this novel instead of making another
      }
      const updated = await api.addChapter(novelId, { text: chapter, title: "", number: null });
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

  const novelOptions: [string, string][] = [
    ["new", "New novel"],
    ...novels.map((n): [string, string] => [n.id, n.title]),
  ];
  const settings = novel
    ? `${labelFor("visual_style", novel.visual_style)} · ${labelFor("narration", novel.narration)} · ${labelFor("novel_language", novel.language)}`
    : "";

  return (
    <div className="gradient-ring rounded-3xl bg-card/80 p-3 shadow-xl shadow-black/5 backdrop-blur-sm sm:p-4">
      <div className="flex flex-wrap items-center gap-2">
        <ChipSelect
          icon={BookText}
          label="Novel"
          value={target}
          options={novelOptions}
          onChange={setTarget}
          className="max-w-full"
        />
        {target === "new" ? (
          <input
            ref={titleRef}
            value={title}
            maxLength={120}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Novel title"
            aria-label="Novel title"
            className="h-9 min-w-0 flex-1 rounded-full border border-border-strong bg-background px-3.5 text-base text-foreground placeholder:text-muted-foreground/70 focus:border-accent focus:outline-none sm:text-sm"
          />
        ) : (
          <span className="text-sm text-muted-foreground">
            {novel ? `Part ${novel.next_chapter}` : "…"}
          </span>
        )}
      </div>

      <textarea
        ref={textRef}
        value={text}
        maxLength={200000}
        onChange={(e) => setText(e.target.value)}
        placeholder="Paste a chapter of your novel…"
        aria-label="Chapter text"
        rows={7}
        className="mt-3 max-h-[45dvh] min-h-40 w-full resize-y rounded-2xl bg-transparent px-1.5 py-1 text-base leading-relaxed text-foreground placeholder:text-muted-foreground/70 focus:outline-none sm:text-sm"
      />

      <label className="mt-2 flex items-center gap-2 rounded-2xl border border-border bg-background px-3 py-2">
        <Sparkles className="size-4 shrink-0 text-accent" />
        <input
          value={brief}
          maxLength={600}
          onChange={(e) => setBrief(e.target.value)}
          placeholder="What to focus on? (optional)"
          aria-label="Request for the writer"
          className="min-w-0 flex-1 bg-transparent text-base text-foreground placeholder:text-muted-foreground/70 focus:outline-none sm:text-sm"
        />
      </label>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {target === "new" ? (
          <>
            <ChipSelect icon={Palette} label="Look" value={look} options={options("visual_style")} onChange={setLook} />
            <ChipSelect
              icon={Mic}
              label="Voice"
              value={voice}
              options={enumOf(config.novel, "narration").map((v): [string, string] => [v, VOICE_CHIP[v] ?? labelFor("narration", v)])}
              onChange={setVoice}
            />
            <ChipSelect
              icon={Languages}
              label="Language"
              value={language}
              options={[
                ["auto", chars >= MIN_CHARS ? `${labelFor("novel_language", lang)} (detected)` : "Detect language"],
                ...options("language", "novel_language"),
              ]}
              onChange={setLanguage}
            />
          </>
        ) : (
          <span className="text-xs text-muted-foreground">{settings}</span>
        )}
        <div className="ml-auto flex items-center gap-3">
          <span className="text-right text-xs leading-tight text-muted-foreground">
            {chars ? `${chars.toLocaleString()} chars` : "No text yet"}
            {estimate && chars >= MIN_CHARS ? (
              <>
                <br />≈ ${estimate.total_usd.toFixed(2)}
              </>
            ) : null}
          </span>
          <button
            type="button"
            onClick={send}
            disabled={sending}
            className="inline-flex h-11 items-center gap-1.5 rounded-full px-5 text-sm font-semibold text-white shadow-md transition-opacity disabled:opacity-60"
            style={{ background: "var(--gradient-accent)" }}
          >
            {sending ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
            {sending ? "Starting" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}
