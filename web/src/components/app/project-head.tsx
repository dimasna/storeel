import { Link } from "@/lib/router";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { STAGES } from "@/lib/labels";
import { cn } from "@/lib/utils";
import type { UseProjectState } from "./project-view";

export function ProjectHead({ project, state }: { project: Project; state: UseProjectState }) {
  const steps = STAGES[project.path] ?? STAGES.video;
  const order = steps.map(([key]) => key);
  const aliases: Record<string, string> = {
    scripting: project.path === "novel" ? "story" : "idea",
    regenerating: "review",
    editing: "review",
    rendering: "done",
  };
  const current = aliases[project.stage] || project.stage;
  const position = Math.max(0, order.indexOf(current));

  return (
    <div className="flex flex-col gap-3">
      <Link
        to={project.novel ? `/n/${project.novel.id}` : "/"}
        className="w-fit text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        {project.novel ? `← ${project.novel.title}` : "← All reels"}
      </Link>
      <input
        aria-label="Reel title"
        defaultValue={project.title}
        maxLength={120}
        onBlur={(e) => {
          const value = e.target.value.trim();
          if (value && value !== project.title)
            state.act(() => api.renameProject(project.id, value));
        }}
        className="-ml-2 w-full rounded-lg border border-transparent bg-transparent px-2 py-1 text-2xl font-bold tracking-tight text-foreground transition-colors hover:border-border focus:border-border focus:bg-card focus:outline-none"
      />
      <ol className="flex flex-wrap gap-1.5">
        {steps.map(([key, label], i) => (
          <li
            key={key}
            className={cn(
              "rounded-full border px-3 py-1 text-xs",
              i < position && "border-border-strong text-foreground",
              i === position && "border-accent bg-accent font-semibold text-accent-foreground",
              i > position && "border-border text-muted-foreground",
            )}
          >
            {label}
          </li>
        ))}
      </ol>
    </div>
  );
}
