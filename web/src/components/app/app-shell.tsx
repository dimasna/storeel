import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ComponentType,
  type ReactNode,
} from "react";
import { KeyRound, Library, PenLine } from "lucide-react";
import { api, apiKey } from "@/lib/api";
import type { ProjectSummary } from "@/lib/types";
import { Link, PANEL_ID, useHashPath } from "@/lib/router";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { LogoLockup, LogoMark } from "@/components/brand/logo";
import { cn } from "@/lib/utils";

// The app frame: one bar across the top (the name, Write and My reels, the theme and the API
// key) over a page of warm paper. A page that brings its own panels (the part studio's chat and
// editor) asks for a bare frame: below the bar, its panels fill the window on large screens.

const ACTIVE_STAGES = new Set(["scripting", "processing", "rendering", "regenerating", "editing"]);

const Frame = createContext<(bare: boolean) => void>(() => {});

/** For a page that draws its own panels on the frame: no shared page around it. */
export function useBareFrame(): void {
  const setBare = useContext(Frame);
  useEffect(() => {
    setBare(true);
    return () => setBare(false);
  }, [setBare]);
}

function useKeyHint(): string {
  return useSyncExternalStore(apiKey.subscribe, apiKey.hint, () => "");
}

/** Whether one of the browser's own reels is being worked on: rechecked when the page changes
 * and, while one is, every few seconds (the bar's My reels shows a lit dot meanwhile). */
function useMaking(path: string): boolean {
  const [reels, setReels] = useState<ProjectSummary[] | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let stale = false;
    api
      .listProjects()
      .then((all) => !stale && setReels(all.filter((p) => !p.read_only)))
      .catch(() => !stale && setReels([]));
    return () => {
      stale = true;
    };
  }, [path, tick]);
  const busy = (reels ?? []).some((p) => ACTIVE_STAGES.has(p.stage));
  useEffect(() => {
    if (!busy) return;
    const timer = window.setTimeout(() => setTick((t) => t + 1), 6000);
    return () => window.clearTimeout(timer);
  }, [busy, reels]);
  return busy;
}

export function Logo({ className, mark }: { className?: string; mark?: boolean }) {
  return (
    <Link to="/" className={cn("flex items-center", className)} aria-label="Storeel Studio home">
      {mark ? <LogoMark size={30} /> : <LogoLockup />}
    </Link>
  );
}

function NavItem({
  to,
  icon: Icon,
  label,
  active,
  lit,
}: {
  to: string;
  icon: ComponentType<{ className?: string }>;
  label: string;
  active: boolean;
  lit?: boolean;
}) {
  return (
    <Link
      to={to}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative inline-flex h-10 items-center gap-2 rounded-full px-4 text-sm font-semibold transition-colors",
        active ? "bg-foreground text-background" : "text-foreground/80 hover:bg-card hover:text-foreground",
      )}
    >
      <Icon className="size-4 shrink-0" />
      {label}
      {lit ? (
        <span
          title="A reel is being made"
          className="absolute right-1.5 top-1.5 size-2 animate-pulse rounded-full"
          style={{ background: "var(--gradient-accent)" }}
        />
      ) : null}
    </Link>
  );
}

function KeyButton({ onClick }: { onClick: () => void }) {
  const hint = useKeyHint();
  return (
    <button
      type="button"
      onClick={onClick}
      title={hint ? "Your Muse / Model API key, kept only in this browser" : "Add your Muse / Model API key"}
      className={cn(
        "inline-flex h-10 items-center gap-2 whitespace-nowrap rounded-full px-4 text-sm font-semibold transition-[filter,colors]",
        hint
          ? "border border-border-strong text-foreground hover:bg-card"
          : "bg-primary text-primary-foreground hover:brightness-105",
      )}
    >
      <KeyRound className="size-4" />
      <span>{hint ? `Key ${hint}` : "Add key"}</span>
    </button>
  );
}

function TopBar({ path, onKeyClick, making }: { path: string; onKeyClick: () => void; making: boolean }) {
  const create = path === "/" || path === "";
  const reels = path.startsWith("/reels");
  return (
    <header className="sticky top-0 z-40 h-16 border-b border-border bg-background/85 backdrop-blur-xl">
      <div className="mx-auto flex h-full max-w-[90rem] items-center gap-2 px-4 sm:px-6">
        <Logo className="mr-auto lg:mr-6" />
        <nav className="hidden items-center gap-1 lg:mr-auto lg:flex">
          <NavItem to="/" icon={PenLine} label="Write" active={create} />
          <NavItem to="/reels" icon={Library} label="My reels" active={reels} lit={making} />
        </nav>
        <Link
          to="/reels"
          aria-label="My reels"
          className={cn(
            "relative grid size-10 place-items-center rounded-full border border-border-strong transition-colors lg:hidden",
            reels ? "text-foreground" : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Library className="size-4" />
          {making ? (
            <span className="absolute right-1 top-1 size-2 animate-pulse rounded-full" style={{ background: "var(--gradient-accent)" }} />
          ) : null}
        </Link>
        <ThemeToggle />
        <KeyButton onClick={onKeyClick} />
      </div>
    </header>
  );
}

export function AppShell({ onKeyClick, children }: { onKeyClick: () => void; children: ReactNode }) {
  const path = useHashPath();
  const [bare, setBare] = useState(false);
  const making = useMaking(path);
  return (
    <Frame.Provider value={setBare}>
      <div className={cn("min-h-dvh", bare ? "bg-frame" : "paper bg-background")}>
        <TopBar path={path} onKeyClick={onKeyClick} making={making} />
        <main
          id={PANEL_ID}
          className={cn(bare ? "lg:fixed lg:inset-x-3 lg:bottom-3 lg:top-[4.75rem] lg:overflow-hidden" : "min-h-[calc(100dvh-4rem)]")}
        >
          <div className={bare ? "px-2 pt-2 lg:h-full lg:p-0" : "mx-auto max-w-6xl px-4 pb-24 pt-6 sm:px-6 lg:px-10 lg:pt-10"}>
            {children}
          </div>
        </main>
      </div>
    </Frame.Provider>
  );
}
