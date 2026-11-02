import { useSyncExternalStore, type MouseEvent, type ReactNode } from "react";

// A dependency-free hash router. The backend serves the SPA at `/` and relies on hash routing
// (#/p/<id>, #/n/<id>), so deep links resolve purely client-side with no server fallback.

function currentHash(): string {
  return window.location.hash.replace(/^#/, "") || "/";
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

/** The current hash path, e.g. "/", "/p/<id>", "/n/<id>". Re-renders on navigation. */
export function useHashPath(): string {
  return useSyncExternalStore(subscribe, currentHash, () => "/");
}

export function navigate(to: string): void {
  const path = to.startsWith("#") ? to.slice(1) : to;
  if (currentHash() === path) return;
  window.location.hash = path;
  window.scrollTo({ top: 0 });
  document.getElementById(PANEL_ID)?.scrollTo({ top: 0 }); // the desktop frame scrolls its panel
}

/** The id of the element that scrolls the page on large screens (the app frame's panel). */
export const PANEL_ID = "panel";

export type Route =
  | { page: "home" }
  | { page: "reels" }
  | { page: "project"; id: string }
  | { page: "novel"; id: string };

export function parseRoute(path: string): Route {
  const project = path.match(/^\/p\/([0-9a-f]{32})/);
  if (project) return { page: "project", id: project[1] };
  const novel = path.match(/^\/n\/([0-9a-f]{32})/);
  if (novel) return { page: "novel", id: novel[1] };
  if (path.startsWith("/reels")) return { page: "reels" };
  return { page: "home" };
}

export function Link({
  to,
  className,
  children,
  ...rest
}: {
  to: string;
  className?: string;
  children: ReactNode;
} & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href">) {
  const href = to.startsWith("#") ? to : `#${to}`;
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey)
      return;
    event.preventDefault();
    navigate(to);
  };
  return (
    <a href={href} className={className} onClick={onClick} {...rest}>
      {children}
    </a>
  );
}
