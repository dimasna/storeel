import { useState } from "react";
import { api, mediaUrl } from "@/lib/api";
import type { Project } from "@/lib/types";
import { useConfig } from "@/lib/config";
import { navigate } from "@/lib/router";
import { ago, megabytes, seconds, expiresIn } from "@/lib/format";
import { Card, Toggle } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";
import type { UseProjectState } from "./project-view";

// ---- Process (paths A and B) --------------------------------------------------------------

export function ProcessSection({ project, state }: { project: Project; state: UseProjectState }) {
  const config = useConfig();
  const processed = Boolean(project.analysis);
  const run = (fresh: boolean) =>
    state.act(
      () => api.process(project.id, fresh),
      processed ? "Updating the pictures…" : "Processing started",
    );
  return (
    <Card title={processed ? "Pictures" : "Process"}>
      <p className="mb-3 text-sm text-muted-foreground">
        {processed
          ? "Update applies style changes and redoes only what changed. Redo makes a new picture for every moment."
          : `Transcribes the speech (Muse Voice Transcribe), plans the pictures (${config.models.plan_name}), finds faces and references (SAM) and draws the pictures (Muse Image).`}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => run(false)}>
          {processed ? "Update pictures" : "Process the video"}
        </Button>
        {processed ? (
          <Button
            onClick={() => {
              if (confirm("Make a new picture for every moment? Each picture costs about $0.01."))
                run(true);
            }}
          >
            Redo all pictures
          </Button>
        ) : null}
      </div>
    </Card>
  );
}

// ---- Render -------------------------------------------------------------------------------

export function RenderSection({ project, state }: { project: Project; state: UseProjectState }) {
  const [fit, setFit] = useState(false);
  const renders = [...project.renders].reverse();
  const differing = Object.values(project.caption_notes || {}).filter((n) => n.script).length;
  return (
    <Card title="Reel">
      {differing ? (
        <p className="mb-3 text-sm text-warning">
          {differing === 1 ? "1 caption line differs" : `${differing} caption lines differ`} from the
          script — check {differing === 1 ? "it" : "them"} under Captions before you render.
        </p>
      ) : null}
      <div className="mb-3">
        <Toggle
          checked={fit}
          onChange={setFit}
          label="Keep under 25 MB (for Messenger and Instagram DMs)"
        />
      </div>
      <Button
        variant="primary"
        className="w-full"
        onClick={() => state.act(() => api.render(project.id, fit ? 25 : null), "Rendering…")}
      >
        {renders.length ? "Render again" : "Render the reel"}
      </Button>
      <div className="mt-4 flex flex-col gap-3">
        {renders.map((r, i) => (
          <div key={r.id} className="flex flex-col gap-2">
            {i === 0 ? (
              <video
                src={mediaUrl(project.id, r.key)}
                controls
                playsInline
                preload="metadata"
                className="w-full rounded-xl border border-border"
              />
            ) : null}
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="text-muted-foreground">
                {seconds(r.duration)} · {megabytes(r.size)}
                {r.fit_mb ? ` · ≤${r.fit_mb} MB` : ""} · {ago(r.created_at)}
              </span>
              <a
                href={mediaUrl(project.id, r.key, true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-strong px-3 py-1.5 text-xs font-semibold transition-colors hover:border-accent/60"
              >
                <Download className="size-3.5" /> Download
              </a>
            </div>
          </div>
        ))}
        {renders.length ? (
          <p className="text-xs text-muted-foreground">{expiresIn(project.updated_at)} — download to keep it.</p>
        ) : null}
      </div>
    </Card>
  );
}

// ---- Usage + delete -----------------------------------------------------------------------

export function UsageSection({ project, state }: { project: Project; state: UseProjectState }) {
  const u = project.usage;
  const rows: [string, string][] = [
    ["Text model", `${u.spark_input_tokens.toLocaleString()} in · ${u.spark_output_tokens.toLocaleString()} out`],
    ["Muse Image", `${u.images} image${u.images === 1 ? "" : "s"}`],
    [
      "SAM",
      `${u.sam_images} image${u.sam_images === 1 ? "" : "s"}` +
        (u.sam_frames ? ` · ${u.sam_frames} video frames` : ""),
    ],
    ["Voice Transcribe", seconds(u.asr_seconds)],
  ];
  return (
    <Card title="Model API usage">
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="text-right text-foreground">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-muted-foreground">
        About ${u.estimated_usd.toFixed(3)} at list prices (estimate).
      </p>
      <div className="mt-4">
        <Button
          variant="danger"
          size="sm"
          onClick={() => {
            if (confirm("Delete this reel and all its files?"))
              state.act(async () => {
                await api.deleteProject(project.id);
                navigate("/");
                return null;
              }, "Deleted");
          }}
        >
          Delete reel
        </Button>
      </div>
    </Card>
  );
}
