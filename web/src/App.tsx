import { useCallback, useEffect, useState } from "react";
import { ConfigProvider } from "@/lib/config";
import { ToastProvider } from "@/lib/toast";
import { useHashPath, parseRoute } from "@/lib/router";
import { Header } from "@/components/app/header";
import { KeyDialog } from "@/components/app/key-dialog";
import { ErrorBoundary } from "@/components/app/error-boundary";
import { HomePage } from "@/pages/home";
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
    <div className="min-h-dvh">
      <Header onKeyClick={openKey} />
      <main className="mx-auto max-w-6xl px-4 pb-24 pt-6 sm:px-6">
        {route.page === "home" && <HomePage />}
        {route.page === "project" && <ProjectPage key={route.id} id={route.id} />}
        {route.page === "novel" && <NovelPage key={route.id} id={route.id} />}
      </main>
      <KeyDialog open={keyOpen} reason={keyReason} onClose={() => setKeyOpen(false)} />
    </div>
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
