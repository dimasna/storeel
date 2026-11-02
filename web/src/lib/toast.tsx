import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { CheckCircle2, AlertCircle, Info, X } from "lucide-react";
import { cn } from "./utils";
import { SPRING_PANEL } from "./ease";

export type ToastKind = "ok" | "error" | "info";
interface Toast {
  id: number;
  message: string;
  kind: ToastKind;
}

interface ToastApi {
  toast: (message: string, kind?: ToastKind) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}

const ICONS = { ok: CheckCircle2, error: AlertCircle, info: Info };
const COLORS: Record<ToastKind, string> = {
  ok: "text-success",
  error: "text-danger",
  info: "text-accent",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);
  const reduce = useReducedMotion();

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, kind: ToastKind = "info") => {
      const id = nextId.current++;
      setToasts((list) => [...list.slice(-3), { id, message, kind }]);
      // Errors stay until dismissed; info/success auto-dismiss.
      if (kind !== "error") window.setTimeout(() => dismiss(id), 5000);
    },
    [dismiss],
  );

  const api = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ol className="pointer-events-none fixed left-1/2 top-[calc(env(safe-area-inset-top)+4.5rem)] z-[100] flex w-[min(92vw,22rem)] -translate-x-1/2 flex-col gap-2 sm:left-auto sm:right-4 sm:translate-x-0">
        <AnimatePresence mode="popLayout">
          {toasts.map((t) => {
            const Icon = ICONS[t.kind];
            return (
              <motion.li
                key={t.id}
                layout
                initial={reduce ? { opacity: 0 } : { opacity: 0, y: -12, filter: "blur(6px)" }}
                animate={reduce ? { opacity: 1 } : { opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={reduce ? { opacity: 0 } : { opacity: 0, y: -8, filter: "blur(6px)" }}
                transition={SPRING_PANEL}
                className="pointer-events-auto flex items-start gap-3 rounded-2xl border border-glass-border bg-glass-strong px-4 py-3 shadow-lg backdrop-blur-xl"
              >
                <Icon className={cn("mt-0.5 size-4 shrink-0", COLORS[t.kind])} />
                <span className="flex-1 text-sm leading-snug text-foreground">{t.message}</span>
                <button
                  onClick={() => dismiss(t.id)}
                  aria-label="Dismiss"
                  className="text-muted-foreground transition-colors hover:text-foreground"
                >
                  <X className="size-4" />
                </button>
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ol>
    </ToastContext.Provider>
  );
}
