import { useId } from "react";
import { cn } from "@/lib/utils";

// Storeel's mark: a bookmark ribbon (the place you stopped in a story) with a play mark on it
// (the story told as a reel), in the lamp's flame, amber to ember. The same drawing is
// web/public/favicon.svg and the app icons; keep them in step.

export const BRAND_STOPS: [number, string][] = [
  [0, "#F6B24A"],
  [0.55, "#EA7A37"],
  [1, "#C9452C"],
];

export const RIBBON = "M12.5 4.5H35.5A5 5 0 0 1 40.5 9.5V43L24 34.6L7.5 43V9.5A5 5 0 0 1 12.5 4.5Z";
export const PLAY = "M20.2 13.6C20.2 12.5 21.4 11.8 22.4 12.4L31.3 17.9C32.2 18.5 32.2 19.8 31.3 20.4L22.4 25.9C21.4 26.5 20.2 25.8 20.2 24.7Z";

export function LogoMark({ size = 32, className, title }: { size?: number; className?: string; title?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg
      viewBox="0 0 48 48"
      width={size}
      height={size}
      className={cn("shrink-0", className)}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <defs>
        <linearGradient id={`storeel-${id}`} x1="8" y1="4" x2="41" y2="43" gradientUnits="userSpaceOnUse">
          {BRAND_STOPS.map(([offset, color]) => (
            <stop key={offset} offset={offset} stopColor={color} />
          ))}
        </linearGradient>
      </defs>
      <path d={RIBBON} fill={`url(#storeel-${id})`} />
      <path d={PLAY} fill="#FFF8EE" />
    </svg>
  );
}

/** The mark and the name: "Storeel" in the storybook serif, "studio" small beside it. */
export function LogoLockup({ size = 30, className }: { size?: number; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <LogoMark size={size} />
      <span className="whitespace-nowrap font-display text-[27px] leading-none tracking-[-0.01em] text-foreground">
        Storeel
        <span className="ml-1.5 align-[0.32em] font-sans text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground max-[420px]:hidden">
          Studio
        </span>
      </span>
    </span>
  );
}
