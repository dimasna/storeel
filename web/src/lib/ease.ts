import type { Transition } from "motion/react";

// Shared easing and spring presets, so motion feels consistent across the app.
export const EASE_OUT = [0.16, 1, 0.3, 1] as const;
export const EASE_IN_OUT = [0.65, 0, 0.35, 1] as const;
export const EASE_OUT_CSS = "cubic-bezier(0.16, 1, 0.3, 1)";

export const SPRING_PRESS: Transition = { type: "spring", stiffness: 420, damping: 28 };
export const SPRING_PANEL: Transition = { type: "spring", stiffness: 320, damping: 34 };
export const SPRING_LAYOUT: Transition = { type: "spring", stiffness: 380, damping: 36 };
export const SPRING_GLIDE: Transition = { type: "spring", stiffness: 260, damping: 30 };

export const DURATION = { fast: 0.16, base: 0.24, slow: 0.4 } as const;
