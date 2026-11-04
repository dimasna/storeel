import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ComponentType,
  type ReactNode,
} from "react";
import { KeyRound, Library, PanelLeftClose, PanelLeftOpen, SquarePen } from "lucide-react";
import { api, apiKey } from "@/lib/api";
import type { ProjectSummary } from "@/lib/types";
import { Link, PANEL_ID, useHashPath } from "@/lib/router";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { LogoLockup, LogoMark } from "@/components/brand/logo";
import { cn } from "@/lib/utils";

// The app frame: on large screens a dark sidebar (create, my reels,
// the projects, the API key) beside one large rounded panel that scrolls on its own; the
// sidebar folds to a rail. A page that brings its own panels (the part studio's chat and
// editor) asks for a bare frame. On phones a slim bar sits on top and the page below it.

const COLLAPSED = "storeel.sidebar";
const ACTIVE_STAGES = new Set(["scripting", "processing", "rendering", "regenerating", "editing"]);

const Frame = createContext<(bare: boolean) => void>(() => {});

/** For a page that draws its own panels on the frame: no shared panel around it. */
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

/** The browser's own reels, newest first, refreshed whenever the page changes and while one
 * of them is being worked on. */
function useRecentReels(path: string): ProjectSummary[] | null {
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
  return reels;
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
  rail,
}: {
  to: string;
  icon: ComponentType<{ className?: string }>;
  label: string;
  active: boolean;
  rail: boolean;
}) {
  return (
    <Link
      to={to}
      title={rail ? label : undefined}
      aria-label={rail ? label : undefined}
      className={cn(
        "flex h-11 items-center gap-3 rounded-xl text-[15px] font-medium transition-colors",
        rail ? "justify-center px-0" : "px-3",
        active
          ? "bg-background text-foreground dark:bg-panel-tile"
          : "text-foreground/85 hover:bg-background/60 hover:text-foreground dark:hover:bg-panel-tile/60",
      )}
    >
      <Icon className="size-[18px] shrink-0" />
      {rail ? null : label}
    </Link>
  );
}

/** A project's state as a dot: white for the open one, a pulsing ring while it is being made,
 * green once it has a reel. */
function StatusDot({ reel, current }: { reel: ProjectSummary; current: boolean }) {
  if (ACTIVE_STAGES.has(reel.stage))
    return <span className="size-2.5 shrink-0 animate-pulse rounded-full border-2 border-success" />;
  if (current) return <span className="size-2.5 shrink-0 rounded-full bg-foreground" />;
  if (reel.renders) return <span className="size-2.5 shrink-0 rounded-full bg-success/80" />;
  return <span className="size-2.5 shrink-0 rounded-full border-2 border-muted-foreground/50" />;
}

function KeyRow({ onClick, rail }: { onClick: () => void; rail: boolean }) {
  const hint = useKeyHint();
  if (rail)
    return (
      <button
        type="button"
        onClick={onClick}
        title={hint ? `API key ${hint}` : "Add your API key"}
        aria-label={hint ? `API key ${hint}` : "Add your API key"}
        className={cn(
          "grid size-11 place-items-center rounded-full transition-colors",
          hint ? "bg-panel-tile text-foreground" : "bg-foreground text-background",
        )}
      >
        <KeyRound className="size-4" />
      </button>
    );
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-w-0 flex-1 items-center gap-3 rounded-2xl px-2 py-2 text-left transition-colors hover:bg-background/60 dark:hover:bg-panel-tile/60"
    >
      <span
        className={cn(
          "grid size-10 shrink-0 place-items-center rounded-full",
          hint ? "bg-panel-tile text-foreground" : "text-white",
        )}
        style={hint ? undefined : { background: "var(--gradient-accent)" }}
      >
        <KeyRound className="size-4" />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-semibold text-foreground">
          {hint ? `Muse key ${hint}` : "Add your API key"}
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {hint ? "Only in this browser" : "Needed to make reels"}
        </span>
      </span>
    </button>
  );
}

function Sidebar({
  path,
  rail,
  onToggle,
  onKeyClick,
}: {
  path: string;
  rail: boolean;
  onToggle: () => void;
  onKeyClick: () => void;
}) {
  const reels = useRecentReels(path);
  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 hidden flex-col pb-3 pt-4 transition-[width] duration-200 lg:flex",
        rail ? "w-[4.5rem] items-center px-2" : "w-64 px-3",
      )}
    >
      <div className={cn("flex items-center", rail ? "flex-col gap-3" : "justify-between pl-2")}>
        <Logo mark={rail} />
        <button
          type="button"
          onClick={onToggle}
          title={rail ? "Open the sidebar" : "Fold the sidebar"}
          aria-label={rail ? "Open the sidebar" : "Fold the sidebar"}
          className="grid size-9 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-background/60 hover:text-foreground dark:hover:bg-panel-tile"
        >
          {rail ? <PanelLeftOpen className="size-[18px]" /> : <PanelLeftClose className="size-[18px]" />}
        </button>
      </div>

      <nav className={cn("mt-6 flex flex-col gap-1", rail && "w-full")}>
        <NavItem to="/" icon={SquarePen} label="Create" active={path === "/" || path === ""} rail={rail} />
        <NavItem to="/reels" icon={Library} label="My reels" active={path.startsWith("/reels")} rail={rail} />
      </nav>

      {rail ? (
        <div className="flex-1" />
      ) : (
        <>
          <p className="mt-7 px-3 text-sm font-medium text-muted-foreground">Projects</p>
          <div className="mt-1.5 flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
            {reels === null ? null : reels.length === 0 ? (
              <p className="px-3 py-2 text-sm text-muted-foreground/80">No projects yet</p>
            ) : (
              reels.slice(0, 14).map((p) => {
                const current = path.startsWith(`/p/${p.id}`);
                return (
                  <Link
                    key={p.id}
                    to={`/p/${p.id}`}
                    title={`${p.title} · ${p.stage}`}
                    className={cn(
                      "flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] transition-colors",
                      current
                        ? "bg-background font-medium text-foreground dark:bg-panel-tile"
                        : "text-foreground/85 hover:bg-background/60 hover:text-foreground dark:hover:bg-panel-tile/60",
                    )}
                  >
                    <StatusDot reel={p} current={current} />
                    <span className="min-w-0 flex-1 truncate">{p.title.replace(/^.* - (Part \d+)/, "$1")}</span>
                  </Link>
                );
              })
            )}
          </div>
        </>
      )}

      <div className={cn("mt-3 flex items-center gap-1", rail && "flex-col gap-2")}>
        <KeyRow onClick={onKeyClick} rail={rail} />
        <ThemeToggle />
      </div>
    </aside>
  );
}

function MobileBar({ path, onKeyClick }: { path: string; onKeyClick: () => void }) {
  const hint = useKeyHint();
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
      <button
        type="button"
        onClick={onKeyClick}
        className={cn(
          "inline-flex h-10 items-center gap-2 whitespace-nowrap rounded-xl px-3 text-sm font-semibold transition-colors",
          hint ? "border border-border-strong text-foreground" : "bg-foreground text-background",
        )}
      >
        <KeyRound className="size-4" />
        <span>{hint || "Add key"}</span>
      </button>
    </header>
  );
}

export function AppShell({ onKeyClick, children }: { onKeyClick: () => void; children: ReactNode }) {
  const path = useHashPath();
  const [bare, setBare] = useState(false);
  const [rail, setRail] = useState(() => localStorage.getItem(COLLAPSED) === "1");
  const toggle = () =>
    setRail((r) => {
      localStorage.setItem(COLLAPSED, r ? "0" : "1");
      return !r;
    });
  return (
    <Frame.Provider value={setBare}>
      <div className="min-h-dvh bg-frame">
        <Sidebar path={path} rail={rail} onToggle={toggle} onKeyClick={onKeyClick} />
        <MobileBar path={path} onKeyClick={onKeyClick} />
        <main
          id={PANEL_ID}
          className={cn(
            "lg:fixed lg:inset-y-2 lg:right-2 lg:transition-[left] lg:duration-200",
            rail ? "lg:left-[4.5rem]" : "lg:left-64",
            bare
              ? "lg:overflow-hidden"
              : "min-h-[calc(100dvh-4rem)] bg-background lg:min-h-0 lg:overflow-y-auto lg:rounded-3xl",
          )}
        >
          <div className={bare ? "px-2 lg:h-full lg:p-0" : "mx-auto max-w-6xl px-4 pb-24 pt-6 sm:px-6 lg:px-10 lg:pt-8"}>
            {children}
          </div>
        </main>
      </div>
    </Frame.Provider>
  );
}
