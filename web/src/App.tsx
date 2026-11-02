import { useCallback, useEffect, useState } from "react";
import { ConfigProvider } from "@/lib/config";
import { ToastProvider } from "@/lib/toast";
import { useHashPath, parseRoute } from "@/lib/router";
import { AppShell } from "@/components/app/app-shell";
import { KeyDialog } from "@/components/app/key-dialog";
import { ErrorBoundary } from "@/components/app/error-boundary";
import { HomePage } from "@/pages/home";
import { ReelsPage } from "@/pages/reels";
import { ProjectPage } from "@/pages/project";
import { NovelPage } from "@/pages/novel";

const NEED_KEY_EVENT = "storeel:need-key";

/** Fire from anywhere to open the API-key dialog. */
export function requestKey(reason?: string) {
  window.dispatchEvent(new CustomEvent(NEED_KEY_EVENT, { detail: reason }));
}

function Shell() {
  const path = useHashPath();
  const route = parseRoute(path);
  const [keyOpen, setKeyOpen] = useState(false);
  const [keyReason, setKeyReason] = useState<string | undefined>();

  useEffect(() => {
    const handler = (e: Event) => {
      setKeyReason((e as CustomEvent<string>).detail);
      setKeyOpen(true);
    };
    window.addEventListener(NEED_KEY_EVENT, handler);
    return () => window.removeEventListener(NEED_KEY_EVENT, handler);
  }, []);

  const openKey = useCallback(() => {
    setKeyReason(undefined);
    setKeyOpen(true);
  }, []);

  return (
    <AppShell onKeyClick={openKey}>
      {route.page === "home" && <HomePage />}
      {route.page === "reels" && <ReelsPage />}
      {route.page === "project" && <ProjectPage key={route.id} id={route.id} />}
      {route.page === "novel" && <NovelPage key={route.id} id={route.id} />}
      <KeyDialog open={keyOpen} reason={keyReason} onClose={() => setKeyOpen(false)} />
    </AppShell>
  );
}

export function App() {
  return (
    <ErrorBoundary>
      <ToastProvider>
        <ConfigProvider>
          <Shell />
        </ConfigProvider>
      </ToastProvider>
    </ErrorBoundary>
  );
}
