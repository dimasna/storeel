import { useState } from "react";
import { api, mediaUrl } from "@/lib/api";
import type { Moment, Project } from "@/lib/types";
import { labelFor } from "@/lib/labels";
import { seconds } from "@/lib/format";
import { Card, Field, Select, Toggle, Banner, Textarea } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { UseProjectState } from "./project-view";

export function PicturesSection({ project, state }: { project: Project; state: UseProjectState }) {
  const analysis = project.analysis;
  if (!analysis)
    return (
      <Card title="Pictures">
        <p className="text-sm text-muted-foreground">Not planned yet.</p>
      </Card>
    );

  return (
    <Card title="Pictures">
      {analysis.summary ? (
        <p className="mb-4 text-sm text-muted-foreground">{analysis.summary}</p>
      ) : null}
      {analysis.entities.length ? (
        <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {analysis.entities.map((e) => (
            <div
              key={e.id}
              title={e.description}
              className="flex items-center gap-2 rounded-xl border border-border bg-background p-2"
            >
              {e.ref_key ? (
                <img src={mediaUrl(project.id, e.ref_key)} alt="" className="size-10 rounded-lg object-cover" />
              ) : (
                <span className="grid size-10 place-items-center rounded-lg bg-card text-muted-foreground">
                  {e.kind[0]?.toUpperCase()}
                </span>
              )}
              <div className="min-w-0">
                <strong className="block truncate text-sm">{e.name}</strong>
                <small className="text-xs text-muted-foreground">
                  {e.ref_source === "video"
                    ? "from your video"
                    : e.ref_source === "generated"
                      ? "reference drawn"
                      : e.kind}
                </small>
              </div>
            </div>
          ))}
        </div>
      ) : null}
      {analysis.moments.length ? (
        <ol className="flex flex-col gap-4">
          {analysis.moments.map((m) => (
            <MomentCard key={m.id} project={project} moment={m} state={state} />
          ))}
        </ol>
      ) : (
        <p className="text-sm text-muted-foreground">
          {project.style.visuals === "off" ? "Pictures are off for this reel." : "No moments were planned."}
        </p>
      )}
    </Card>
  );
}

function MomentCard({
  project,
  moment,
  state,
}: {
  project: Project;
  moment: Moment;
  state: UseProjectState;
}) {
  const [prompt, setPrompt] = useState(moment.prompt);

  return (
    <li
      className={cn(
        "flex gap-4 rounded-2xl border border-border bg-background p-3",
        !moment.enabled && "opacity-50",
      )}
    >
      <div className="w-24 shrink-0">
        {moment.asset ? (
          <a href={mediaUrl(project.id, moment.asset.key)} target="_blank" rel="noopener noreferrer">
            <img
              src={mediaUrl(project.id, moment.asset.key)}
              alt={moment.prompt}
              loading="lazy"
              className="w-full rounded-lg border border-border object-cover"
            />
          </a>
        ) : (
          <div className="grid aspect-[9/16] w-full place-items-center rounded-lg bg-card text-2xl text-muted-foreground">
            {moment.error ? "!" : "…"}
          </div>
        )}
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">
            {seconds(moment.start)} – {seconds(moment.end)}
          </span>
          <Toggle
            checked={moment.enabled}
            onChange={(checked) => state.act(() => api.editMoment(project.id, moment.id, { enabled: checked }))}
            label="show"
          />
        </div>
        <p className="text-sm italic text-foreground">“{moment.quote}”</p>
        {moment.note ? <p className="text-xs text-muted-foreground">{moment.note}</p> : null}
        {moment.error ? <Banner tone="error">{moment.error}</Banner> : null}
        <Field label="Shown as">
          <Select
            value={moment.display}
            onChange={(e) =>
              state.act(
                () => api.editMoment(project.id, moment.id, { display: e.target.value }),
                "Making a picture in the new shape…",
              )
            }
          >
            {["overlay", "cutout", "cutaway"].map((v) => (
              <option key={v} value={v}>
                {labelFor("display", v)}
              </option>
            ))}
          </Select>
        </Field>
        <details>
          <summary className="cursor-pointer text-xs text-muted-foreground">Picture prompt</summary>
          <Textarea
            rows={3}
            maxLength={1200}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            className="mt-2"
          />
          <Button
            size="sm"
            className="mt-2"
            onClick={() =>
              state.act(
                () =>
                  api.regenerateMoment(
                    project.id,
                    moment.id,
                    prompt.trim() && prompt !== moment.prompt ? prompt.trim() : undefined,
                  ),
                "Regenerating the picture…",
              )
            }
          >
            Regenerate
          </Button>
        </details>
      </div>
    </li>
  );
}
