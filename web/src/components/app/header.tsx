import { useSyncExternalStore } from "react";
import { KeyRound } from "lucide-react";
import { apiKey } from "@/lib/api";
import { Link } from "@/lib/router";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { cn } from "@/lib/utils";

function useKeyHint(): string {
  return useSyncExternalStore(apiKey.subscribe, apiKey.hint, () => "");
}

export function Header({ onKeyClick }: { onKeyClick: () => void }) {
  const hint = useKeyHint();
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/70 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Link to="/" className="flex items-center gap-2 text-lg font-bold tracking-tight">
          <span className="grid size-7 place-items-center rounded-lg" style={{ background: "var(--gradient-accent)" }}>
            <svg viewBox="0 0 32 32" className="size-4">
              <path d="M12 9l12 7-12 7z" fill="white" />
            </svg>
          </span>
          Storeel <span className="gradient-text">Studio</span>
        </Link>
        <div className="flex items-center gap-2">
          <button
            onClick={onKeyClick}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
              hint
                ? "border-success/40 text-success hover:border-success/70"
                : "border-warning/50 text-warning hover:border-warning/80",
            )}
          >
            <KeyRound className="size-3.5" />
            {hint ? `API key ${hint}` : "Add API key"}
          </button>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
