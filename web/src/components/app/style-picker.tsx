import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import { Check, Scissors, Sparkles } from "lucide-react";
import { LOOKS, THEME_CARDS, preview, themeCard, type Look, type ThemeCard } from "@/lib/styles";
import { cn } from "@/lib/utils";

// The reel styles shown by example (see lib/styles.ts): the home page's gallery, after
// OpusClip's grid of styles, and a compact picker for the home card and a reel's style card.
// Every example is the same part, so only the style changes from one to the next.

/** A style's example filling its box: the loop while it is on screen and `play` allows it,
 * the still otherwise (and always with reduced motion). */
export function StyleVideo({
  look,
  theme,
  play = true,
  className,
}: {
  look: string;
  theme: string;
  play?: boolean;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const box = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [seen, setSeen] = useState(false);
  const example = preview(look, theme);

  useEffect(() => {
    const element = box.current;
    if (!element || typeof IntersectionObserver === "undefined") return setSeen(true);
    const observer = new IntersectionObserver(([entry]) => setSeen(entry.isIntersecting), { threshold: 0.35 });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const element = video.current;
    if (!element) return;
    if (play && seen) element.play().catch(() => {}); // a browser may refuse; the still stays
    else element.pause();
  }, [play, seen, example?.video]);

  return (
    <div ref={box} className={cn("absolute inset-0 bg-panel-tile", className)}>
      {example ? (
        reduce ? (
          <img src={example.still} alt="" loading="lazy" decoding="async" className="size-full object-cover" />
        ) : (
          <video
            key={example.video}
            ref={video}
            src={example.video}
            poster={example.still}
            muted
            loop
            playsInline
            preload="none"
            aria-hidden
            className="size-full object-cover"
          />
        )
      ) : null}
    </div>
  );
}

/** What is behind the speaker: dalang, scene or studio (the two cut-out looks cost SAM time). */
export function LookSwitch({
  value,
  onChange,
  className,
}: {
  value: Look;
  onChange: (look: Look) => void;
  className?: string;
}) {
  return (
    <div role="radiogroup" aria-label="Behind you" className={cn("grid grid-cols-3 gap-1 rounded-xl bg-panel-tile p-1", className)}>
      {LOOKS.map((item) => (
        <button
          key={item.look}
          type="button"
          role="radio"
          aria-checked={value === item.look}
          title={item.blurb}
          onClick={() => onChange(item.look)}
          className={cn(
            "inline-flex h-9 min-w-0 items-center justify-center gap-1.5 rounded-lg px-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
            value === item.look ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {item.cutout ? <Scissors className="size-3.5 shrink-0" aria-hidden /> : null}
          <span className="truncate">{item.name}</span>
        </button>
      ))}
    </div>
  );
}

/** The home page's gallery: every theme in the look chosen above it. */
export function StyleGallery({
  chosen,
  onUse,
}: {
  chosen?: { look: string; theme: string } | null;
  onUse: (look: Look, theme: string) => void;
}) {
  const [look, setLook] = useState<Look>("dalang");
  const about = LOOKS.find((l) => l.look === look);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
        <span className="text-sm font-semibold text-foreground">Behind you</span>
        <LookSwitch value={look} onChange={setLook} className="w-full sm:w-80" />
        <span className="text-sm text-muted-foreground">
          {about?.blurb}. SAM 3.1 cuts you out, about $0.24 for 100 seconds
          {about?.cutout ? "" : ", so you can step back under the pictures"}
        </span>
      </div>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {THEME_CARDS.map((card) => (
          <GalleryTile
            key={card.theme}
            look={look}
            card={card}
            chosen={chosen?.look === look && chosen?.theme === card.theme}
            onUse={() => onUse(look, card.theme)}
          />
        ))}
      </ul>
    </div>
  );
}

function GalleryTile({
  look,
  card,
  chosen,
  onUse,
}: {
  look: Look;
  card: ThemeCard;
  chosen: boolean;
  onUse: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onUse}
        aria-label={`Use the ${card.name} style`}
        className="group flex w-full flex-col gap-2 text-left focus-visible:outline-none"
      >
        <span
          className={cn(
            "relative block aspect-[9/16] w-full overflow-hidden rounded-xl transition-shadow group-focus-visible:ring-2 group-focus-visible:ring-accent",
            chosen && "ring-2 ring-accent",
          )}
        >
          <StyleVideo look={look} theme={card.theme} />
          {/* Hover (pointer screens): how to use it; a tap on a touch screen uses it at once. */}
          <span className="absolute inset-x-2 bottom-2 hidden items-center justify-center gap-1.5 rounded-[10px] bg-white py-2 text-[13px] font-semibold text-black opacity-0 shadow-sm transition-opacity duration-200 group-hover:opacity-100 [@media(hover:hover)]:flex">
            <Sparkles className="size-3.5" /> Use this style
          </span>
          {chosen ? (
            <span className="absolute right-2 top-2 grid size-6 place-items-center rounded-full bg-accent text-accent-foreground">
              <Check className="size-3.5" />
            </span>
          ) : null}
        </span>
        <span className="flex flex-col px-0.5">
          <span className="text-sm font-semibold text-foreground">
            {card.name} <span className="font-normal text-muted-foreground">· {card.genre}</span>
          </span>
          <span className="line-clamp-2 text-xs leading-snug text-muted-foreground">{card.blurb}</span>
        </span>
      </button>
    </li>
  );
}

/** A compact picker: the look, then a row of themes, "auto" first when it is offered. The
 * chosen theme plays; the others show their still. `autoTheme` is what "auto" comes to (the
 * novel's genre), shown on its tile. */
export function StylePicker({
  look,
  theme,
  onChange,
  autoTheme,
  autoLabel,
  offerAuto = true,
}: {
  look: Look;
  theme: string;
  onChange: (look: Look, theme: string) => void;
  autoTheme?: string | null;
  autoLabel?: string;
  offerAuto?: boolean;
}) {
  const options = offerAuto ? ["auto", ...THEME_CARDS.map((c) => c.theme)] : THEME_CARDS.map((c) => c.theme);
  return (
    <div className="flex flex-col gap-3">
      <LookSwitch value={look} onChange={(next) => onChange(next, theme)} />
      {/* Room around the tiles (and the snap point) for the chosen one's ring; the row scrolls
          inside whatever holds it instead of widening it (an auto-sized grid column would grow). */}
      <div
        className="-m-1 flex snap-x scroll-px-1 gap-2 overflow-x-auto p-1 [contain:inline-size]"
        role="radiogroup"
        aria-label="Theme"
      >
        {options.map((option) => {
          const shown = option === "auto" ? autoTheme || "none" : option;
          const card = themeCard(option);
          const selected = option === theme;
          const name = option === "auto" ? "Auto" : card?.name ?? option;
          const sub = option === "auto" ? autoLabel || "By genre" : card?.genre ?? "";
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(look, option)}
              className="group flex w-[5.75rem] shrink-0 snap-start flex-col gap-1.5 text-left focus-visible:outline-none"
            >
              <span
                className={cn(
                  "relative block aspect-[9/16] w-full overflow-hidden rounded-lg transition-shadow group-focus-visible:ring-2 group-focus-visible:ring-accent/60",
                  selected && "ring-2 ring-accent",
                )}
              >
                {option === "auto" && !autoTheme ? (
                  <span className="absolute inset-0 grid place-items-center bg-panel-tile text-muted-foreground">
                    <Sparkles className="size-5" />
                  </span>
                ) : (
                  <StyleVideo look={look} theme={shown} play={selected} />
                )}
                {selected ? (
                  <span className="absolute right-1.5 top-1.5 grid size-5 place-items-center rounded-full bg-accent text-accent-foreground">
                    <Check className="size-3" />
                  </span>
                ) : null}
              </span>
              <span className="flex flex-col px-0.5 leading-tight">
                <span className="truncate text-xs font-semibold text-foreground">{name}</span>
                <span className="truncate text-[11px] text-muted-foreground">{sub}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
