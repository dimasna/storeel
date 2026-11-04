import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  AudioLines,
  BookOpen,
  ChevronDown,
  Eye,
  Film,
  Lightbulb,
  Palette,
  PenLine,
  Play,
  Scissors,
  type LucideIcon,
} from "lucide-react";
import { LogoMark } from "@/components/brand/logo";
import { motion } from "motion/react";
import { api } from "@/lib/api";
import type { ProjectSummary } from "@/lib/types";
import { useToast } from "@/lib/toast";
import { labelFor } from "@/lib/labels";
import { Link, navigate } from "@/lib/router";
import { EASE_OUT } from "@/lib/ease";
import { ChapterComposer, type ReelStyle } from "@/components/app/chapter-composer";
import { Showcase } from "@/components/app/showcase";
import { HAS_PREVIEWS, lookName, themeCard, type Look } from "@/lib/styles";

// The home page: a badge, one line of headline, the card, the showcase of every style (the
// looks, themes and effects by example, and the picture styles), the questions people ask, and
// a footer: a closing card to start a reel, the five models in order, and one line of links.

// Lines from the stories in the gallery, set as a faint texture behind the headline.
const TEXTURE = (
  "THE BELL RANG ONCE MORE THOUGH NO ONE WAS AT THE DOOR · BESOK DIA MENIKAHI ORANG LAIN · " +
  "SHE NEVER SENT THE LETTER · THE WITNESS WAS ALREADY GONE · ONE JUMP ONE CHANCE · THE QUEEN " +
  "WOULD NOT KNEEL · THE CAT ATE THE WEDDING CAKE · IT PLAYED BY ITSELF AT MIDNIGHT · I WOKE UP " +
  "AS THE VILLAIN · SIGN IT OR LOSE EVERYTHING · "
).repeat(9);

const FAQ: [string, string][] = [
  [
    "What is Storeel?",
    "A studio that turns a chapter of your novel into a short vertical reel you narrate. Muse Spark writes the part (a hook, the story in short beats, a poll and a call to action), you read it from a teleprompter, and the reel comes out with captions, the novel's characters drawn by Muse Image, a Part badge and an end card. Each chapter is one part of a series, and the characters look the same from part to part.",
  ],
  [
    "What do I need?",
    "A chapter of your novel (in Indonesian or English), a phone or laptop camera to read it on, and your own Meta Model API key. Recording works in the browser, line by line, or you can upload one video of you reading the whole part.",
  ],
  [
    "Which Meta models does it use?",
    "Muse Spark writes the part, checks its storyboard against the chapter and edits the reel when you ask in the chat. Muse Voice Transcribe hears your narration for the captions. Muse Wonder watches a video you bring and plans where each picture goes. Muse Image draws the characters, objects and places. SAM 3.1 cuts them out of their background.",
  ],
  [
    "What does a reel cost?",
    "About $0.25 to $0.35 at Meta's list prices for a first part, billed to your key: writing and checking the part, eight to twelve pictures and the transcription. The card shows the estimate before you send. Rendering is free, and later parts reuse the characters already drawn.",
  ],
  [
    "Where do my key and my videos go?",
    "Your key stays in this browser and travels only with the request that starts a job; the server keeps it in memory until the job ends. There is no login: each browser sees only the reels it made. Reels and recordings are deleted 24 hours after you last touch them, so download yours.",
  ],
  [
    "What does the finished reel look like?",
    "An MP4 at 1080×1920, usually one and a half to two minutes long, with word-by-word captions, the pictures, a poll screen and an end card that sends viewers to the full chapter. Ask the chat for changes (caption colours, a character's outfit, a picture) and render again.",
  ],
];

// The footer's row of the five Meta models, roughly in the order a reel goes through them.
const MADE_WITH: [LucideIcon, string, string][] = [
  [PenLine, "Muse Spark", "Writes the part, checks it against the chapter and edits it in the chat"],
  [AudioLines, "Muse Voice Transcribe", "Hears your reading for word-by-word captions"],
  [Eye, "Muse Wonder", "Watches your video and plans where each picture goes"],
  [Palette, "Muse Image", "Draws the characters, objects and places"],
  [Scissors, "SAM 3.1", "Cuts them out of their background"],
];

function useShowcase(): ProjectSummary | null {
  const [reel, setReel] = useState<ProjectSummary | null>(null);
  useEffect(() => {
    api
      .listProjects()
      .then((all) => setReel(all.find((p) => p.read_only && p.renders > 0) ?? null))
      .catch(() => setReel(null));
  }, []);
  return reel;
}

export function HomePage() {
  const { toast } = useToast();
  const showcase = useShowcase();
  const [look, setLook] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);
  const [reelStyle, setReelStyle] = useState<ReelStyle | null>(null);
  const [styleFlash, setStyleFlash] = useState(false);
  const card = useRef<HTMLDivElement>(null);
  const flashTimer = useRef<number | null>(null);
  const styleTimer = useRef<number | null>(null);

  const pickLook = (value: string) => {
    setLook(value);
    card.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    setFlash(true);
    if (flashTimer.current) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlash(false), 1800);
    toast(`${labelFor("visual_style", value)} it is. Paste a chapter to start.`, "info");
  };

  const pickStyle = (nextLook: Look, theme: string) => {
    setReelStyle({ look: nextLook, theme });
    card.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    setStyleFlash(true);
    if (styleTimer.current) window.clearTimeout(styleTimer.current);
    styleTimer.current = window.setTimeout(() => setStyleFlash(false), 1800);
    const name = `${themeCard(theme)?.name ?? theme} · ${lookName(nextLook)}`;
    toast(`${name} it is. Paste a chapter to start.`, "info");
  };

  const create = async (path: "video" | "idea") => {
    try {
      const project = await api.createProject(path);
      navigate(`/p/${project.id}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  return (
    <div className="relative flex flex-col">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-8 h-[24rem] select-none overflow-hidden break-all font-mono text-[12px] font-medium leading-[1.3] tracking-[0.24em] text-foreground/[0.045] [mask-image:radial-gradient(ellipse_58%_52%_at_50%_38%,black_10%,transparent)]"
      >
        {TEXTURE}
      </div>

      <section className="relative mx-auto flex w-full max-w-3xl flex-col items-center pt-6 text-center sm:pt-10">
        <motion.span
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: EASE_OUT }}
          className="rainbow-ring rounded-full bg-background/60 px-3.5 py-1 text-sm font-medium text-foreground backdrop-blur-sm"
        >
          Storeel Studio · made with Meta Muse
        </motion.span>
        <motion.h1
          initial={{ opacity: 0, y: 12, filter: "blur(6px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          transition={{ duration: 0.5, delay: 0.05, ease: EASE_OUT }}
          className="mt-5 text-balance text-[2.6rem] font-bold leading-[1.08] tracking-[-0.03em] sm:text-4xl"
        >
          Turn your novel into reels by chatting with AI
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1, ease: EASE_OUT }}
          className="mt-3 max-w-xl text-balance text-base text-muted-foreground sm:text-lg"
        >
          Paste a chapter, read the part from a teleprompter, and get a reel with captions and drawn
          characters in minutes.
        </motion.p>

        <motion.div
          ref={card}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.15, ease: EASE_OUT }}
          className="mt-8 w-full scroll-mt-24 text-left"
        >
          <ChapterComposer
            look={look}
            onLook={setLook}
            highlightLook={flash}
            reelStyle={reelStyle}
            onReelStyle={setReelStyle}
            highlightStyle={styleFlash}
          />
        </motion.div>

        <div className="mt-6 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
          {showcase ? (
            <Link to={`/p/${showcase.id}`} className="inline-flex items-center gap-1.5 transition-colors hover:text-foreground">
              <Play className="size-3.5" /> Watch a finished part
            </Link>
          ) : null}
          <button onClick={() => create("video")} className="inline-flex items-center gap-1.5 transition-colors hover:text-foreground">
            <Film className="size-3.5" /> Or start from your video
          </button>
          <button onClick={() => create("idea")} className="inline-flex items-center gap-1.5 transition-colors hover:text-foreground">
            <Lightbulb className="size-3.5" /> From an idea
          </button>
        </div>
      </section>

      {HAS_PREVIEWS ? (
        <section className="mt-16 sm:mt-24">
          <h2 className="text-2xl font-semibold tracking-tight">Choose a style for your reel</h2>
          <p className="mb-5 mt-1 text-sm text-muted-foreground">
            The same part, made by Storeel from one video, in every look, theme and effect, and the
            picture styles Muse Image draws in. Pick one and your part is made that way; you can still
            change it before you render.
          </p>
          <Showcase
            look={reelStyle?.look ?? "dalang"}
            theme={reelStyle?.theme ?? "auto"}
            pictureLook={look}
            onStyle={pickStyle}
            onPictureLook={pickLook}
          />
        </section>
      ) : null}

      <section className="mt-20 grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:gap-10 sm:mt-28">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight">Before you start</h2>
          <p className="mt-2 text-lg text-muted-foreground">What Storeel needs, what it makes and what it costs.</p>
        </div>
        <div className="flex flex-col gap-1">
          {FAQ.map(([q, a], i) => (
            <details key={q} open={i === 0} className="group rounded-2xl px-5 py-4 transition-colors open:bg-card sm:px-6">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-base font-semibold text-foreground sm:text-lg [&::-webkit-details-marker]:hidden">
                {q}
                <ChevronDown className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
              </summary>
              <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">{a}</p>
            </details>
          ))}
        </div>
      </section>

      <footer className="mt-20 flex flex-col gap-10 sm:mt-28">
        <div className="relative overflow-hidden rounded-3xl px-6 py-10 text-center text-white sm:px-10 sm:py-14" style={{ background: "var(--gradient-accent)" }}>
          <div aria-hidden className="pointer-events-none absolute -right-16 -top-16 size-56 rounded-full bg-white/10 blur-2xl" />
          <div aria-hidden className="pointer-events-none absolute -bottom-20 -left-10 size-64 rounded-full bg-white/10 blur-3xl" />
          <h2 className="relative text-balance text-3xl font-bold tracking-tight sm:text-4xl">Your next chapter is one reel away</h2>
          <p className="relative mx-auto mt-3 max-w-xl text-balance text-white/80">
            Paste it, read it, and post it. Your key, your voice, your characters.
          </p>
          <div className="relative mt-7 flex flex-wrap items-center justify-center gap-3">
            <button
              onClick={() => card.current?.scrollIntoView({ behavior: "smooth", block: "center" })}
              className="inline-flex items-center gap-2 rounded-full bg-white px-5 py-2.5 text-sm font-semibold text-[#0064e0] shadow-sm transition-transform hover:scale-[1.03]"
            >
              <BookOpen className="size-4" /> Paste a chapter
            </button>
            <button
              onClick={() => create("video")}
              className="inline-flex items-center gap-2 rounded-full bg-white/15 px-5 py-2.5 text-sm font-semibold text-white ring-1 ring-white/40 transition-colors hover:bg-white/25"
            >
              <Film className="size-4" /> Use my video
            </button>
            <button
              onClick={() => create("idea")}
              className="inline-flex items-center gap-2 rounded-full bg-white/15 px-5 py-2.5 text-sm font-semibold text-white ring-1 ring-white/40 transition-colors hover:bg-white/25"
            >
              <Lightbulb className="size-4" /> Start from an idea
            </button>
          </div>
        </div>

        <div>
          <p className="text-center text-xs font-semibold uppercase tracking-[0.2em] text-muted-foreground">How a reel is made</p>
          <ol className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
            {MADE_WITH.map(([Icon, model, job], i) => (
              <li key={model} className="relative flex flex-col gap-2 rounded-2xl bg-card p-4 ring-1 ring-border last:col-span-2 lg:last:col-span-1">
                <div className="flex items-center justify-between">
                  <span className="grid size-8 place-items-center rounded-full bg-primary/10 text-primary">
                    <Icon className="size-4" />
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">0{i + 1}</span>
                </div>
                <p className="text-sm font-semibold text-foreground">{model}</p>
                <p className="text-xs leading-relaxed text-muted-foreground">{job}</p>
                {i < MADE_WITH.length - 1 ? (
                  <ArrowRight aria-hidden className="absolute -right-3 top-1/2 z-10 hidden size-4 -translate-y-1/2 rounded-full bg-background text-muted-foreground lg:block" />
                ) : null}
              </li>
            ))}
          </ol>
        </div>

        <div className="flex flex-col items-center gap-3 border-t border-border py-6 text-sm text-muted-foreground sm:flex-row sm:justify-between">
          <span className="inline-flex items-center gap-2">
            <LogoMark size={20} /> Storeel · reels are kept for 24 hours
          </span>
          <span className="flex flex-wrap items-center justify-center gap-x-5 gap-y-1">
            <Link to="/reels" className="hover:text-foreground">
              My reels
            </Link>
            <a href="https://cerebralvalley.ai/e/meta-ai-developer-hackathon" target="_blank" rel="noopener noreferrer" className="hover:text-foreground">
              Meta AI Developer Hackathon
            </a>
          </span>
        </div>
      </footer>
    </div>
  );
}
