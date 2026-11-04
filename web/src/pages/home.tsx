import { useEffect, useRef, useState } from "react";
import { BookOpenText, ChevronDown, Clapperboard, Film, Lightbulb, Mic, Play } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { api } from "@/lib/api";
import type { ProjectSummary } from "@/lib/types";
import { useToast } from "@/lib/toast";
import { labelFor } from "@/lib/labels";
import { Link, navigate } from "@/lib/router";
import { EASE_OUT } from "@/lib/ease";
import { cn } from "@/lib/utils";
import { ChapterComposer, type ReelStyle } from "@/components/app/chapter-composer";
import { Gallery } from "@/components/app/gallery";
import { StyleGallery, StyleVideo } from "@/components/app/style-picker";
import { HAS_PREVIEWS, THEME_CARDS, lookName, themeCard, type Look } from "@/lib/styles";

// The home page, a storyteller's desk by lamplight: the promise in a serif headline beside a
// reel playing on a phone (the example part, theme by theme), the composer under it, three
// steps from chapter to reel, the reel styles and the picture looks by example, the questions
// people ask, and a short footer.

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
    "Muse Spark writes the part, checks its storyboard against the chapter and edits the reel when you ask in the chat. Muse Image draws the characters, objects and places. SAM 3.1 cuts them out of their background. Muse Voice Transcribe hears your narration for the captions.",
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

// The hero's phone plays the example part in each theme in turn (a tap picks one).
const HERO_THEMES = ["horror", "romance", "mystery", "legend", "drama"];

function HeroReel() {
  const reduce = useReducedMotion();
  const [at, setAt] = useState(0);
  const [held, setHeld] = useState(false);
  useEffect(() => {
    if (reduce || held) return;
    const timer = window.setInterval(() => setAt((i) => (i + 1) % HERO_THEMES.length), 5200);
    return () => window.clearInterval(timer);
  }, [reduce, held]);
  const theme = HERO_THEMES[at];
  const card = themeCard(theme);
  return (
    <figure className="relative flex flex-col items-center" onMouseEnter={() => setHeld(true)} onMouseLeave={() => setHeld(false)}>
      <div className="relative aspect-[9/16] w-[17.5rem] overflow-hidden rounded-[2.4rem] border-[7px] border-[#1f1a15] bg-[#1f1a15] shadow-[0_40px_80px_-36px_rgb(80_45_15/0.55)] xl:w-[19rem] dark:border-[#2c251e]">
        <StyleVideo key={theme} look="dalang" theme={theme} />
        <span className="absolute left-1/2 top-2 h-4 w-20 -translate-x-1/2 rounded-full bg-[#1f1a15] dark:bg-[#2c251e]" />
      </div>
      <figcaption className="mt-5 flex flex-col items-center gap-3">
        <span className="text-sm text-muted-foreground">
          One reading, styled as <span className="font-display text-lg italic text-foreground">{card?.name}</span>
          <span className="text-muted-foreground"> · {card?.genre}</span>
        </span>
        <span className="flex gap-1.5" role="radiogroup" aria-label="Theme">
          {HERO_THEMES.map((t, i) => (
            <button
              key={t}
              type="button"
              role="radio"
              aria-checked={i === at}
              aria-label={themeCard(t)?.name}
              onClick={() => setAt(i)}
              className={cn("h-1.5 rounded-full transition-all", i === at ? "w-6 bg-accent" : "w-1.5 bg-border-strong hover:bg-muted-foreground")}
            />
          ))}
        </span>
      </figcaption>
    </figure>
  );
}

const STEPS: { icon: typeof BookOpenText; title: string; body: string }[] = [
  {
    icon: BookOpenText,
    title: "Paste a chapter",
    body: "Muse Spark writes the part: a hook, the story in short beats, a poll and a call to action, checked against your chapter.",
  },
  {
    icon: Mic,
    title: "Read it out loud",
    body: "Line by line from the teleprompter, or one video of the whole part. Your voice and your face tell it.",
  },
  {
    icon: Clapperboard,
    title: "Post the reel",
    body: "Captions, your characters drawn by Muse Image, effects and a theme for the genre. Change anything by asking.",
  },
];

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
      {/* The lamp's glow, behind the headline. */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-[-9rem] -z-0 h-[40rem] w-[min(78rem,140vw)] -translate-x-1/2"
        style={{ background: "var(--glow)" }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-8 h-[22rem] select-none overflow-hidden break-all font-display text-[15px] italic leading-[1.35] tracking-[0.06em] text-foreground/[0.05] [mask-image:radial-gradient(ellipse_60%_55%_at_30%_35%,black_10%,transparent)]"
      >
        {TEXTURE}
      </div>

      <section className="relative grid items-center gap-10 pt-2 sm:pt-4 lg:grid-cols-[minmax(0,1.12fr)_minmax(0,0.88fr)] lg:gap-12">
        <div className="flex min-w-0 flex-col items-start">
          <motion.span
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: EASE_OUT }}
            className="stamp bg-background/70 px-3.5 py-1 text-[13px] font-medium text-muted-foreground backdrop-blur-sm"
          >
            Storeel Studio · made with Meta Muse
          </motion.span>
          <motion.h1
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, delay: 0.05, ease: EASE_OUT }}
            className="mt-5 font-display text-[3.35rem] leading-[0.96] tracking-[-0.015em] text-foreground sm:text-[4.4rem] xl:text-[5.1rem]"
          >
            Your chapter,
            <br />
            <span className="italic text-accent">told by you.</span>
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1, ease: EASE_OUT }}
            className="mt-5 max-w-xl text-pretty text-[17px] leading-relaxed text-muted-foreground sm:text-lg"
          >
            Paste a chapter of your novel. Storeel writes the part, draws your characters and cuts the
            reel; you read it out loud.
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

          <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-muted-foreground">
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
        </div>
        {HAS_PREVIEWS ? (
          <motion.div
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2, ease: EASE_OUT }}
            className="hidden justify-center lg:flex"
          >
            <HeroReel />
          </motion.div>
        ) : null}
      </section>

      <section className="mt-16 grid gap-3 sm:mt-24 sm:grid-cols-3 sm:gap-4">
        {STEPS.map(({ icon: Icon, title, body }, i) => (
          <div key={title} className="relative rounded-[22px] border border-border bg-card p-5 sm:p-6">
            <span className="font-display text-5xl leading-none text-accent/80">{i + 1}</span>
            <Icon className="absolute right-5 top-6 size-5 text-muted-foreground" />
            <h3 className="mt-3 text-base font-semibold text-foreground">{title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{body}</p>
          </div>
        ))}
      </section>

      {HAS_PREVIEWS ? (
        <section className="mt-16 sm:mt-24">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">Reel styles</p>
          <h2 className="mt-1 font-display text-[2.4rem] leading-tight tracking-[-0.01em]">One reading, every style.</h2>
          <p className="mb-6 mt-1 max-w-2xl text-sm text-muted-foreground">
            The same part, made by Storeel from one video, in every look and theme ({THEME_CARDS.length} themes).
            Pick one and your part is made that way; you can still change it before you render.
          </p>
          <StyleGallery chosen={reelStyle} onUse={pickStyle} />
        </section>
      ) : null}

      <section className={HAS_PREVIEWS ? "mt-16 sm:mt-20" : "mt-16 sm:mt-24"}>
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">Picture looks</p>
        <h2 className="mt-1 font-display text-[2.4rem] leading-tight tracking-[-0.01em]">How your characters are drawn.</h2>
        <p className="mb-6 mt-1 max-w-2xl text-sm text-muted-foreground">
          Frames of novel parts, drawn by Muse Image. Pick one and every part of your novel is drawn that way.
        </p>
        <Gallery onUse={pickLook} />
      </section>

      <section className="mt-20 grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:gap-10 sm:mt-28">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">Questions</p>
          <h2 className="mt-1 font-display text-[2.6rem] leading-tight tracking-[-0.01em]">Before you start.</h2>
          <p className="mt-2 text-lg text-muted-foreground">What Storeel needs, what it makes and what it costs.</p>
        </div>
        <div className="flex flex-col divide-y divide-border border-y border-border">
          {FAQ.map(([q, a], i) => (
            <details key={q} open={i === 0} className="group px-1 py-4 sm:px-2">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-base font-semibold text-foreground sm:text-lg [&::-webkit-details-marker]:hidden">
                {q}
                <ChevronDown className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
              </summary>
              <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">{a}</p>
            </details>
          ))}
        </div>
      </section>

      <footer className="mt-16 grid gap-8 border-t border-border pt-10 text-sm sm:grid-cols-3">
        <div className="flex flex-col gap-3">
          <p className="font-semibold text-foreground">Make</p>
          <button onClick={() => card.current?.scrollIntoView({ behavior: "smooth", block: "center" })} className="w-fit text-muted-foreground hover:text-foreground">
            A novel part
          </button>
          <button onClick={() => create("video")} className="w-fit text-muted-foreground hover:text-foreground">
            A reel from your video
          </button>
          <button onClick={() => create("idea")} className="w-fit text-muted-foreground hover:text-foreground">
            A reel from an idea
          </button>
        </div>
        <div className="flex flex-col gap-3">
          <p className="font-semibold text-foreground">Made with</p>
          <span className="text-muted-foreground">Muse Spark: writing, checks and the chat</span>
          <span className="text-muted-foreground">Muse Image: characters and scenes</span>
          <span className="text-muted-foreground">SAM 3.1: cut-outs</span>
          <span className="text-muted-foreground">Muse Voice Transcribe: captions</span>
        </div>
        <div className="flex flex-col gap-3">
          <p className="font-semibold text-foreground">About</p>
          <a
            href="https://cerebralvalley.ai/e/meta-ai-developer-hackathon"
            target="_blank"
            rel="noopener noreferrer"
            className="w-fit text-muted-foreground hover:text-foreground"
          >
            Built for the Meta AI Developer Hackathon
          </a>
          <Link to="/reels" className="w-fit text-muted-foreground hover:text-foreground">
            My reels
          </Link>
          <span className="text-muted-foreground">Reels are kept for 24 hours</span>
        </div>
      </footer>
    </div>
  );
}
