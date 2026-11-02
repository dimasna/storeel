import { useEffect, useRef } from "react";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { JOB_NAMES } from "@/lib/labels";
import { jobActive } from "@/lib/use-project";
import { Button } from "@/components/ui/button";
import { ProgressBar, Banner } from "@/components/ui/primitives";
import type { UseProjectState } from "./project-view";

export function JobPanel({ project, state }: { project: Project; state: UseProjectState }) {
  const job = project.job;
  const logRef = useRef<HTMLPreElement>(null);
  const active = jobActive(project);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [job?.log]);

  if (!job) return null;

  return (
    <section className="rounded-3xl border border-border bg-card/60 p-5 backdrop-blur-sm">
      <div className="mb-3 flex items-center gap-3">
        <strong className="text-sm font-semibold">{JOB_NAMES[job.kind] || job.kind}</strong>
        <span className="flex-1 text-sm text-muted-foreground">
          {job.status === "queued" ? "waiting for a worker…" : job.step || ""}
        </span>
        {active && (
          <Button
            size="sm"
            disabled={job.cancel_requested}
            onClick={() => state.act(() => api.cancelJob(job.id), "Cancelling…")}
          >
            {job.cancel_requested ? "Cancelling…" : "Cancel"}
          </Button>
        )}
      </div>
      <ProgressBar value={job.progress || 0} />
      {job.status === "failed" ? (
        <Banner tone="error" className="mt-3">
          {job.error || "failed"}
        </Banner>
      ) : null}
      {job.log ? (
        <details open={job.status === "failed"} className="mt-3">
          <summary className="cursor-pointer text-xs text-muted-foreground">Log</summary>
          <pre
            ref={logRef}
            className="mt-2 max-h-48 overflow-auto rounded-xl bg-background p-3 font-mono text-xs leading-relaxed text-muted-foreground"
          >
            {job.log}
          </pre>
        </details>
      ) : null}
    </section>
  );
}
