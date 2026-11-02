import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { motion, useReducedMotion } from "motion/react";
import { Moon, Sun } from "lucide-react";
import { SPRING_PRESS } from "@/lib/ease";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const reduce = useReducedMotion();
  useEffect(() => setMounted(true), []);

  const dark = resolvedTheme === "dark";
  return (
    <motion.button
      type="button"
      aria-label="Toggle theme"
      whileTap={reduce ? undefined : { scale: 0.9 }}
      transition={SPRING_PRESS}
      onClick={() => setTheme(dark ? "light" : "dark")}
      className="inline-flex size-9 items-center justify-center rounded-full border border-border-strong text-muted-foreground transition-colors hover:text-foreground"
    >
      {mounted && dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </motion.button>
  );
}
