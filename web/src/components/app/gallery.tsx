import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";
import { Sparkles } from "lucide-react";
import { GALLERY, type GalleryTile } from "@/lib/gallery";
import { labelFor } from "@/lib/labels";
import { cn } from "@/lib/utils";

// The gallery under the home page's card, after OpusClip's grid of creator styles: tall tiles
// that play like muted shorts. Each is a frame of a novel part in one picture look, read word
// by word; "Use this look" puts that look on the card above.

/** One clock for every tile, so the captions advance together and cost one timer. */
function useTick(ms: number, on: boolean): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!on) return;
    const timer = window.setInterval(() => setTick((t) => t + 1), ms);
    return () => window.clearInterval(timer);
  }, [ms, on]);
  return tick;
}

function Tile({ tile, tick, onUse }: { tile: GalleryTile; tick: number; onUse: (look: string) => void }) {
  const words = tile.caption.split(" ");
  // A short rest after the last word, then the line again; each tile starts at its own word.
  const cycle = words.length + 2;
  const at = (tick + tile.id.length) % cycle;
  const look = labelFor("visual_style", tile.look);
  return (
    <li className="group relative aspect-[9/16] overflow-hidden rounded-xl bg-panel-tile">
      <div className="size-full transition-transform duration-300 ease-[cubic-bezier(.25,1,.5,1)] group-hover:scale-[1.07] motion-reduce:transition-none">
        <img
          src={tile.image}
          alt={tile.description}
          loading="lazy"
          decoding="async"
          className="tile-push size-full object-cover"
          style={{ animationDelay: `-${(tile.id.length % 9) * 1.1}s` }}
        />
      </div>
      {/* The reel's own words: the part badge and title on top, the caption low in the frame. */}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/45 via-transparent to-black/55" />
      <div className="pointer-events-none absolute inset-x-2.5 top-2.5 flex items-center gap-1.5">
        <span className="shrink-0 whitespace-nowrap rounded-md bg-[#e8303a] px-1.5 py-0.5 text-[11px] font-extrabold leading-none text-white shadow-sm">
          Part {tile.part}
        </span>
        <span className="truncate text-[11px] font-bold leading-none text-white [text-shadow:0_1px_3px_rgb(0_0_0/0.8)]">
          {tile.title}
        </span>
      </div>
      <p className="pointer-events-none absolute inset-x-3 bottom-[29%] text-center text-[15px] font-extrabold leading-tight text-white [text-shadow:0_2px_6px_rgb(0_0_0/0.85)] sm:bottom-[24%] sm:text-base">
        {words.map((word, i) => (
          <span key={i}>
            <span
              className={cn(
                "-mx-[0.12em] rounded-md px-[0.12em] transition-colors duration-150",
                i === at ? "bg-[#e8303a]" : "bg-transparent",
              )}
            >
              {word}
            </span>{" "}
          </span>
        ))}
      </p>
      {/* Hover (always shown on touch screens): what the look is, and a way to use it. */}
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-black/75 opacity-0 transition-opacity duration-300 group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100" />
      <div className="absolute inset-x-2 bottom-2 flex flex-col gap-1.5 opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100">
        <p className="truncate px-1 text-[11px] leading-tight text-white/80">
          <span className="font-semibold text-white">{look}</span> · {tile.genre}
        </p>
        <button
          type="button"
          onClick={() => onUse(tile.look)}
          aria-label={`Use the ${look} look`}
          className="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-[10px] bg-white text-[13px] font-semibold text-black transition-colors hover:bg-white/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
        >
          <Sparkles className="size-3.5" /> Use this look
        </button>
      </div>
    </li>
  );
}

export function Gallery({ onUse }: { onUse: (look: string) => void }) {
  const reduce = useReducedMotion();
  const tick = useTick(520, !reduce);
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {GALLERY.map((tile) => (
        <Tile key={tile.id} tile={tile} tick={tick} onUse={onUse} />
      ))}
    </ul>
  );
}
