import { forwardRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

// ---- Card / Section -----------------------------------------------------------------------

export function Card({
  title,
  children,
  className,
  actions,
}: {
  title?: ReactNode;
  children: ReactNode;
  className?: string;
  actions?: ReactNode;
}) {
  return (
    <section
      className={cn(
        "rounded-[22px] border border-border bg-card p-5 shadow-[0_1px_0_rgb(0_0_0/0.02)] sm:p-6",
        className,
      )}
    >
      {(title || actions) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title ? <h2 className="font-display text-[22px] leading-tight text-foreground">{title}</h2> : <span />}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function SubHeading({ children }: { children: ReactNode }) {
  return (
    <h3 className="mt-2 mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">
      {children}
    </h3>
  );
}

// ---- Field --------------------------------------------------------------------------------

export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("flex flex-col gap-1.5", className)}>
      <span className="text-xs font-semibold text-muted-foreground">{label}</span>
      {children}
      {hint ? <span className="text-xs text-muted-foreground/80">{hint}</span> : null}
    </label>
  );
}

// ---- Input / Textarea / Select ------------------------------------------------------------

const fieldClasses =
  "w-full rounded-xl border border-input bg-background px-3 py-2 text-sm text-foreground " +
  "placeholder:text-muted-foreground/60 transition-colors " +
  "focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30";

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} className={cn(fieldClasses, className)} {...rest} />;
  },
);

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cn(fieldClasses, "resize-y leading-relaxed", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...rest }, ref) {
    return (
      <select ref={ref} className={cn(fieldClasses, "cursor-pointer appearance-none", className)} {...rest}>
        {children}
      </select>
    );
  },
);

// ---- Pill / Banner ------------------------------------------------------------------------

type PillTone = "default" | "ok" | "warn" | "bad" | "accent";
const PILL_TONE: Record<PillTone, string> = {
  default: "border-border-strong text-muted-foreground",
  ok: "border-success/40 text-success",
  warn: "border-warning/40 text-warning",
  bad: "border-danger/40 text-danger",
  accent: "border-accent/40 text-accent",
};

export function Pill({
  tone = "default",
  children,
  title,
}: {
  tone?: PillTone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium",
        PILL_TONE[tone],
      )}
    >
      {children}
    </span>
  );
}

type BannerTone = "error" | "warn" | "info";
const BANNER_TONE: Record<BannerTone, string> = {
  error: "border-danger/40 bg-danger/10 text-danger",
  warn: "border-warning/40 bg-warning/10 text-warning",
  info: "border-accent/40 bg-accent/10 text-accent",
};

export function Banner({
  tone = "info",
  children,
  className,
}: {
  tone?: BannerTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border px-3.5 py-2.5 text-sm leading-relaxed",
        BANNER_TONE[tone],
        className,
      )}
    >
      {children}
    </div>
  );
}

// ---- Progress bar -------------------------------------------------------------------------

export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-border-strong">
      <div
        className="h-full rounded-full transition-[width] duration-300"
        style={{
          width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`,
          background: "var(--gradient-accent)",
        }}
      />
    </div>
  );
}

// ---- Toggle (checkbox) --------------------------------------------------------------------

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className="inline-flex cursor-pointer select-none items-center gap-2 text-sm text-foreground">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 accent-accent"
      />
      {label}
    </label>
  );
}
