import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import { BookText, Film, Home, KeyRound, Library, Lightbulb } from "lucide-react";
import { api, apiKey } from "@/lib/api";
import type { ProjectSummary } from "@/lib/types";
import { Link, PANEL_ID, useHashPath } from "@/lib/router";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { LogoLockup } from "@/components/brand/logo";
import { cn } from "@/lib/utils";

// The app frame, as in OpusClip's studio: on large screens a dark sidebar (navigation, your
// recent reels, the API key) beside one large rounded panel that scrolls on its own; on phones
// a slim bar on top and the page below it.

function useKeyHint(): string {
  return useSyncExternalStore(apiKey.subscribe, apiKey.hint, () => "");
}

/** The browser's own reels, newest first, refreshed whenever the page changes. */
function useRecentReels(path: string): ProjectSummary[] | null {
  const [reels, setReels] = useState<ProjectSummary[] | null>(null);
  useEffect(() => {
    let stale = false;
    api
      .listProjects()
      .then((all) => !stale && setReels(all.filter((p) => !p.read_only)))
      .catch(() => !stale && setReels([]));
    return () => {
      stale = true;
    };
  }, [path]);
  return reels;
}

export function Logo({ className }: { className?: string }) {
  return (
    <Link to="/" className={cn("flex items-center", className)} aria-label="Storeel Studio home">
      <LogoLockup />
    </Link>
  );
}

function KeyButton({ onClick, full }: { onClick: () => void; full?: boolean }) {
  const hint = useKeyHint();
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-10 items-center justify-center gap-2 whitespace-nowrap rounded-xl px-4 text-sm font-semibold transition-colors max-sm:px-3",
        full && "w-full",
        hint
          ? "border border-border-strong text-foreground hover:border-accent/60"
          : "bg-foreground text-background hover:opacity-90",
      )}
    >
      <KeyRound className="size-4" />
      {hint ? (
        <span>
          <span className="max-sm:hidden">API key </span>
          {hint}
        </span>
      ) : (
        <span>
          Add <span className="max-sm:hidden">API </span>key
        </span>
      )}
    </button>
  );
}

const STAGE_HINT: Record<string, string> = {
  story: "to write",
  scripting: "writing…",
  record: "to record",
  ready: "to process",
  processing: "making…",
  rendering: "rendering…",
  review: "to render",
  done: "ready",
};

function NavItem({ to, icon: Icon, label, active }: { to: string; icon: typeof Home; label: string; active: boolean }) {
  return (
    <Link
      to={to}
      className={cn(
        "flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors",
        active
          ? "bg-background text-foreground dark:bg-panel-tile"
          : "text-muted-foreground hover:bg-background/60 hover:text-foreground dark:hover:bg-panel-tile/60",
      )}
    >
      <Icon className="size-4" /> {label}
    </Link>
  );
}

function Sidebar({ path, onKeyClick }: { path: string; onKeyClick: () => void }) {
  const reels = useRecentReels(path);
  return (
    <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col px-3 pb-3 pt-4 lg:flex">
      <Logo className="px-2" />
      <nav className="mt-6 flex flex-col gap-1">
        <NavItem to="/" icon={Home} label="Home" active={path === "/" || path === ""} />
        <NavItem to="/reels" icon={Library} label="My reels" active={path.startsWith("/reels")} />
      </nav>

      <p className="mt-7 px-3 text-xs font-medium text-muted-foreground">Recent</p>
      <div className="mt-1 flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
        {reels === null ? null : reels.length === 0 ? (
          <p className="px-3 py-2 text-sm text-muted-foreground/80">No reels yet</p>
        ) : (
          reels.slice(0, 12).map((p) => {
            const active = path.startsWith(`/p/${p.id}`);
            const Icon = p.path === "novel" ? BookText : p.path === "idea" ? Lightbulb : Film;
            return (
              <Link
                key={p.id}
                to={`/p/${p.id}`}
                title={p.title}
                className={cn(
                  "group flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-background text-foreground dark:bg-panel-tile"
                    : "text-muted-foreground hover:bg-background/60 hover:text-foreground dark:hover:bg-panel-tile/60",
                )}
              >
                <Icon className="size-3.5 shrink-0" />
                <span className="min-w-0 flex-1 truncate">{p.title.replace(/^.* - (Part \d+)/, "$1")}</span>
                <span className="shrink-0 text-[11px] text-muted-foreground/70">{STAGE_HINT[p.stage] ?? ""}</span>
              </Link>
            );
          })
        )}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <KeyButton onClick={onKeyClick} full />
        </div>
        <ThemeToggle />
      </div>
    </aside>
  );
}

function MobileBar({ path, onKeyClick }: { path: string; onKeyClick: () => void }) {
  return (
    <header className="sticky top-0 z-40 flex items-center gap-2 bg-frame/80 px-4 py-3 backdrop-blur-xl lg:hidden">
      <Logo className="mr-auto" />
      <Link
        to="/reels"
        aria-label="My reels"
        className={cn(
          "grid size-9 place-items-center rounded-full border border-border-strong transition-colors",
          path.startsWith("/reels") ? "text-foreground" : "text-muted-foreground hover:text-foreground",
        )}
      >
        <Library className="size-4" />
      </Link>
      <ThemeToggle />
      <KeyButton onClick={onKeyClick} />
    </header>
  );
}

export function AppShell({ onKeyClick, children }: { onKeyClick: () => void; children: ReactNode }) {
  const path = useHashPath();
  return (
    <div className="min-h-dvh bg-frame">
      <Sidebar path={path} onKeyClick={onKeyClick} />
      <MobileBar path={path} onKeyClick={onKeyClick} />
      <main
        id={PANEL_ID}
        className="min-h-[calc(100dvh-4rem)] bg-background lg:fixed lg:inset-y-2 lg:left-64 lg:right-2 lg:min-h-0 lg:overflow-y-auto lg:rounded-3xl"
      >
        <div className="mx-auto max-w-6xl px-4 pb-24 pt-6 sm:px-6 lg:px-10 lg:pt-8">{children}</div>
      </main>
    </div>
  );
}
