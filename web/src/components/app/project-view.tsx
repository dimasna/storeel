import { useSyncExternalStore } from "react";
import { apiKey } from "@/lib/api";
import type { Project } from "@/lib/types";
import { jobActive, type UseProject } from "@/lib/use-project";
import { requestKey } from "@/App";
import { cn } from "@/lib/utils";
import { Banner } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { ProjectHead } from "./project-head";
import { JobPanel } from "./job-panel";
import { StyleSection } from "./style-section";
import { ProcessSection, RenderSection, UsageSection } from "./side-sections";
import { ClipsSection } from "./clips-section";
import { TranscriptSection } from "./transcript-section";
import { PicturesSection } from "./pictures-section";
import { IdeaSection, ScriptSection } from "./idea-section";
import { AgentDock } from "./agent-dock";
import { ShowcaseView } from "./showcase-view";
import {
  PartSection,
  StorySection,
  TakesSection,
  PartProcessSection,
  PartPicturesSection,
} from "./novel-part-sections";

export type UseProjectState = UseProject;

function useHasKey(): boolean {
  return useSyncExternalStore(apiKey.subscribe, () => Boolean(apiKey.get()), () => false);
}

export function ProjectView({ state }: { state: UseProject }) {
  const project = state.project as Project;
  const hasKey = useHasKey();
  const locked = jobActive(project);

  if (project.read_only) return <ShowcaseView project={project} />;

  const inputsReady =
    project.path === "video"
      ? project.clips.length > 0
      : project.path === "novel" && project.clips.length
        ? true
        : Boolean(project.script && project.script.scenes.every((s) => s.take));

  const keyProblem =
    project.error && /\b(401|403)\b|authentication|API key/i.test(project.error);

  return (
    <div className="flex flex-col gap-5">
      <ProjectHead project={project} state={state} />

      {!hasKey ? (
        <Banner tone="warn" className="flex flex-wrap items-center gap-2">
          <span>
            Add your Muse / Model API key to transcribe, plan and draw pictures. Rendering works
            without it.
          </span>
          <Button size="sm" onClick={() => requestKey()}>
            Add API key
          </Button>
        </Banner>
      ) : null}

      {project.error && !locked ? (
        <Banner tone="error" className="flex flex-wrap items-center gap-2">
          <span>Last job failed: {project.error}</span>
          {keyProblem ? (
            <Button size="sm" onClick={() => requestKey()}>
              Update API key
            </Button>
          ) : null}
        </Banner>
      ) : null}

      {project.job && project.job.kind !== "agent" && (locked || project.job.status === "failed") ? (
        <JobPanel project={project} state={state} />
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
        <div className={cn("flex flex-col gap-5", locked && "pointer-events-none opacity-60")}>
          {project.path === "novel" ? (
            <>
              <PartSection project={project} state={state} />
              {project.story ? (
                <>
                  <StorySection project={project} state={state} />
                  <TakesSection project={project} state={state} />
                </>
              ) : null}
            </>
          ) : project.path === "idea" ? (
            <>
              <IdeaSection project={project} state={state} />
              {project.script ? <ScriptSection project={project} state={state} /> : null}
            </>
          ) : (
            <ClipsSection project={project} state={state} />
          )}

          {project.path === "novel" && project.part_pictures ? (
            <>
              <PartPicturesSection project={project} />
              <TranscriptSection project={project} state={state} />
            </>
          ) : project.analysis || project.transcript ? (
            <>
              <PicturesSection project={project} state={state} />
              <TranscriptSection project={project} state={state} />
            </>
          ) : null}
        </div>

        <div className={cn("flex flex-col gap-5", locked && "pointer-events-none opacity-60")}>
          <StyleSection project={project} state={state} />
          {project.path === "novel"
            ? (inputsReady || project.part_pictures) && (
                <PartProcessSection project={project} state={state} />
              )
            : (inputsReady || project.analysis) && (
                <ProcessSection project={project} state={state} />
              )}
          {project.analysis ? <RenderSection project={project} state={state} /> : null}
          <UsageSection project={project} state={state} />
        </div>
      </div>

      {/* The editor works on captions and pictures, so it appears once the reel is processed. */}
      {project.transcript ? <AgentDock project={project} state={state} /> : null}
    </div>
  );
}
