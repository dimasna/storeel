import { forwardRef } from "react";
import { motion, useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";
import { SPRING_PRESS } from "@/lib/ease";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg" | "icon";

const VARIANT: Record<Variant, string> = {
  primary:
    "bg-primary text-primary-foreground border border-transparent hover:brightness-105 shadow-[0_1px_0_rgb(0_0_0/0.08),0_6px_18px_-8px_color-mix(in_srgb,var(--primary)_80%,transparent)]",
  secondary:
    "bg-background text-foreground border border-border-strong hover:border-accent/60 hover:bg-card",
  ghost: "bg-transparent text-muted-foreground border border-transparent hover:text-foreground hover:bg-card",
  danger: "bg-transparent text-danger border border-danger/40 hover:bg-danger/10",
};

// Pills: the studio's buttons are round-ended, like its chips and its badges.
const SIZE: Record<Size, string> = {
  sm: "h-8 px-3.5 text-xs gap-1.5 rounded-full",
  md: "h-10 px-4.5 text-sm gap-2 rounded-full",
  lg: "h-12 px-6 text-base gap-2 rounded-full",
  icon: "size-8 rounded-full",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", className, children, disabled, ...rest },
  ref,
) {
  const reduce = useReducedMotion();
  return (
    <motion.button
      ref={ref}
      disabled={disabled}
      whileTap={reduce || disabled ? undefined : { scale: 0.96 }}
      transition={SPRING_PRESS}
      className={cn(
        "inline-flex select-none items-center justify-center font-semibold transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
      {...(rest as React.ComponentProps<typeof motion.button>)}
    >
      {children}
    </motion.button>
  );
});
