import { useId } from "react";
import { cn } from "@/lib/utils";

// Storeel's mark: an open book whose right page is a play button (stories that play), white on
// the brand gradient. The same drawing is web/public/favicon.svg; keep the two in step.

export const BRAND_STOPS: [number, string][] = [
  [0, "#3AA5FF"],
  [0.5, "#0082FB"],
  [1, "#0058CC"],
];

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
        <linearGradient id={`storeel-${id}`} x1="3" y1="2" x2="45" y2="46" gradientUnits="userSpaceOnUse">
          {BRAND_STOPS.map(([offset, color]) => (
            <stop key={offset} offset={offset} stopColor={color} />
          ))}
        </linearGradient>
      </defs>
      <rect width="48" height="48" rx="12" fill={`url(#storeel-${id})`} />
      <g transform="translate(-0.8 0)">
        <g opacity="0.58">
          <path
            d="M22 15.6C18.8 13.7 15 12.9 11.4 13.3V34.5C15 34.1 18.8 34.9 22 36.8Z"
            fill="#fff"
            stroke="#fff"
            strokeWidth="2"
            strokeLinejoin="round"
          />
        </g>
        <path d="M28 17.6V34.4L38.6 26Z" fill="#fff" stroke="#fff" strokeWidth="4" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

/** The mark and the name on one line: "Storeel" set tight and bold, "Studio" quieter beside it. */
export function LogoLockup({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark size={size} />
      <span className="whitespace-nowrap text-[19px] font-semibold leading-none tracking-[-0.03em] text-foreground">
        Storeel<span className="ml-[0.28em] font-medium text-muted-foreground max-[420px]:hidden">Studio</span>
      </span>
    </span>
  );
}
