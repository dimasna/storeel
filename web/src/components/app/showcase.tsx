import { useMemo, useState } from "react";
import { useReducedMotion } from "motion/react";
import { Check, Scissors, Sparkles } from "lucide-react";
import { GALLERY } from "@/lib/gallery";
import { EFFECT_CARDS, effectPreview } from "@/lib/effects";
import { labelFor } from "@/lib/labels";
import { LOOKS, THEME_CARDS, type Look } from "@/lib/styles";
import { cn } from "@/lib/utils";
import { LoopVideo, StyleVideo } from "./style-picker";
import { PictureFrame, useTick } from "./gallery";

// The home page's showcase: every way a reel can look, by example, in one grid of tall tiles
// that play like muted shorts, filtered by a row of chips: the looks (what is behind you), the
// themes (the genre's dress), the effects (free, drawn at render) and the picture styles (how
// Muse Image draws the characters). Every look, theme and effect is the same example part, so
// only that changes from one tile to the next. A look, a theme or a picture style can be put on
// the card above with one tap; the effects say how they are set.

type Kind = "look" | "theme" | "effect" | "picture";

const FILTERS: { kind: Kind | "all"; label: string }[] = [
  { kind: "all", label: "All" },
  { kind: "look", label: "Looks" },
  { kind: "theme", label: "Themes" },
  { kind: "effect", label: "Effects" },
  { kind: "picture", label: "Picture styles" },
];

const KIND_LABEL: Record<Kind, string> = {
  look: "Look",
  theme: "Theme",
  effect: "Effect",
  picture: "Picture style",
};

interface Entry {
  key: string;
  kind: Kind;
  name: string;
  sub: string;
  blurb: string;
  chosen: boolean;
  media: () => React.ReactNode;
  /** The tile's action: put it on the card (looks, themes, picture styles). */
  use?: () => void;
  useLabel?: string;
  /** For an effect: how it is set, shown instead of an action. */
  how?: string;
}

function EffectVideo({ id }: { id: string }) {
  const example = effectPreview(id);
  return <LoopVideo video={example?.video} still={example?.still} />;
}

export function Showcase({
  look,
  theme,
  pictureLook,
  onStyle,
  onPictureLook,
}: {
  look: Look;
  theme: string;
  pictureLook: string | null;
  onStyle: (look: Look, theme: string) => void;
  onPictureLook: (visualStyle: string) => void;
}) {
  const [filter, setFilter] = useState<Kind | "all">("all");
  const reduce = useReducedMotion();
  const tick = useTick(520, !reduce);

  const entries = useMemo<Entry[]>(() => {
    const looks: Entry[] = LOOKS.map((item) => ({
      key: `look-${item.look}`,
      kind: "look",
      name: item.name,
      sub: item.cutout ? "cut out by SAM 3.1" : "",
      blurb: item.blurb,
      chosen: look === item.look,
      media: () => <StyleVideo look={item.look} theme={theme === "auto" ? "none" : theme} />,
      use: () => onStyle(item.look, theme),
      useLabel: "Use this look",
    }));
    const themes: Entry[] = THEME_CARDS.map((card) => ({
      key: `theme-${card.theme}`,
      kind: "theme",
      name: card.name,
      sub: card.genre,
      blurb: card.blurb,
      chosen: theme === card.theme,
      media: () => <StyleVideo look={look} theme={card.theme} />,
      use: () => onStyle(look, card.theme),
      useLabel: "Use this theme",
    }));
    const effects: Entry[] = EFFECT_CARDS.map((card) => ({
      key: `effect-${card.id}`,
      kind: "effect",
      name: card.name,
      sub: "",
      blurb: card.blurb,
      chosen: false,
      media: () => <EffectVideo id={card.id} />,
      how: card.how,
    }));
    const pictures: Entry[] = GALLERY.map((tile) => ({
      key: `picture-${tile.id}`,
      kind: "picture",
      name: labelFor("visual_style", tile.look),
      sub: tile.genre,
      blurb: `“${tile.title}”, drawn by Muse Image`,
      chosen: pictureLook === tile.look,
      media: () => <PictureFrame tile={tile} tick={tick} />,
      use: () => onPictureLook(tile.look),
      useLabel: "Use this style",
    }));
    return [...looks, ...themes, ...effects, ...pictures];
  }, [look, theme, pictureLook, onStyle, onPictureLook, tick]);

  const counts = useMemo(() => {
    const out: Record<string, number> = { all: entries.length };
    for (const entry of entries) out[entry.kind] = (out[entry.kind] ?? 0) + 1;
    return out;
  }, [entries]);
  const shown = filter === "all" ? entries : entries.filter((e) => e.kind === filter);

  return (
    <div className="flex flex-col gap-5">
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0" role="tablist" aria-label="Show">
        {FILTERS.map(({ kind, label }) => (
          <button
            key={kind}
            type="button"
            role="tab"
            aria-selected={filter === kind}
            onClick={() => setFilter(kind)}
            className={cn(
              "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium transition-colors",
              filter === kind
                ? "border-transparent bg-foreground text-background"
                : "border-border-strong text-muted-foreground hover:border-foreground/30 hover:text-foreground",
            )}
          >
            {label}
            <span className={cn("tabular-nums", filter === kind ? "text-background/70" : "text-muted-foreground/70")}>
              {counts[kind] ?? 0}
            </span>
          </button>
        ))}
      </div>

      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {shown.map((entry) => (
          <ShowcaseTile key={entry.key} entry={entry} />
        ))}
      </ul>
    </div>
  );
}

function ShowcaseTile({ entry }: { entry: Entry }) {
  return (
    <li className="group flex flex-col gap-2">
      <div
        className={cn(
          "relative aspect-[9/16] w-full overflow-hidden rounded-xl bg-panel-tile transition-shadow",
          entry.chosen && "ring-2 ring-accent",
        )}
      >
        {entry.media()}
        {entry.chosen ? (
          <span className="absolute right-2 top-2 grid size-6 place-items-center rounded-full bg-accent text-accent-foreground">
            <Check className="size-3.5" />
          </span>
        ) : null}
        {entry.use ? (
          <button
            type="button"
            onClick={entry.use}
            aria-label={`${entry.useLabel}: ${entry.name}`}
            className="absolute inset-x-2 bottom-2 inline-flex h-9 items-center justify-center gap-1.5 rounded-[10px] bg-white text-[13px] font-semibold text-black opacity-0 shadow-sm transition-opacity duration-200 hover:bg-white/90 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white group-hover:opacity-100 [@media(hover:none)]:opacity-100"
          >
            <Sparkles className="size-3.5" /> {entry.useLabel}
          </button>
        ) : entry.how ? (
          <span className="pointer-events-none absolute inset-x-2 bottom-2 rounded-[10px] bg-black/60 px-2.5 py-1.5 text-center text-[11px] font-medium leading-tight text-white backdrop-blur-sm">
            {entry.how}
          </span>
        ) : null}
      </div>
      <div className="flex flex-col px-0.5">
        <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-accent">
          {entry.kind === "look" && entry.sub ? <Scissors className="size-2.5" aria-hidden /> : null}
          {KIND_LABEL[entry.kind]}
        </span>
        <span className="text-sm font-semibold text-foreground">
          {entry.name}
          {entry.sub ? <span className="font-normal text-muted-foreground"> · {entry.sub}</span> : null}
        </span>
        <span className="line-clamp-2 text-xs leading-snug text-muted-foreground">{entry.blurb}</span>
      </div>
    </li>
  );
}
