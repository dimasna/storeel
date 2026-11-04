import { useEffect, useState } from "react";
import type { GalleryTile } from "@/lib/gallery";
import { cn } from "@/lib/utils";

// The picture styles, as frames of novel parts: a picture drawn by Muse Image in one look, with
// the reel's own words laid over it (the part badge and title, a caption read word by word).
// The home page's showcase shows one per picture style.

/** One clock for every tile, so the captions advance together and cost one timer. */
export function useTick(ms: number, on: boolean): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!on) return;
    const timer = window.setInterval(() => setTick((t) => t + 1), ms);
    return () => window.clearInterval(timer);
  }, [ms, on]);
  return tick;
}

/** A picture style's frame, filling its box. */
export function PictureFrame({ tile, tick }: { tile: GalleryTile; tick: number }) {
  const words = tile.caption.split(" ");
  // A short rest after the last word, then the line again; each tile starts at its own word.
  const cycle = words.length + 2;
  const at = (tick + tile.id.length) % cycle;
  return (
    <div className="absolute inset-0">
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
    </div>
  );
}

