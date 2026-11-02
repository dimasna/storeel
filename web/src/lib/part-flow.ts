// Where a novel part is in its first pass, as the part studio's checklist shows it. Everything
// is derived from the project and its latest job; nothing about the flow is stored.

import type { Job, Project, Story } from "./types";
import { jobActive } from "./use-project";

export type StepId = "write" | "check" | "record" | "transcribe" | "draw" | "render";
export type StepState = "todo" | "active" | "yours" | "done" | "failed";

export interface FlowStep {
  id: StepId;
  label: string;
  state: StepState;
  detail: string;
}

export const STEP_LABELS: Record<StepId, string> = {
  write: "Write the part: hook, beats, poll, call to action",
  check: "Check the storyboard against the chapter",
  record: "Your turn: record the part",
  transcribe: "Transcribe your narration",
  draw: "Draw the characters and scenes",
  render: "Render the reel",
};

const ORDER: StepId[] = ["write", "check", "record", "transcribe", "draw", "render"];

/** The step a running (or failed) job is on, from its kind and the name of its stage. */
export function jobStep(job: Job | null): StepId | null {
  if (!job) return null;
  const step = job.step || "";
  if (job.kind === "story") {
    if (step.startsWith("Checking") || step.startsWith("Fixing")) return "check";
    return "write";
  }
  if (job.kind === "process") {
    if (step.startsWith("Drawing") || step.startsWith("Finding")) return "draw";
    if (step.startsWith("Rendering")) return "render";
    return "transcribe";
  }
  if (job.kind === "render") return "render";
  return null; // the editor's jobs come after the first pass
}

export interface Recording {
  takes: number;
  recorded: number;
  video: boolean;
  complete: boolean;
}

export function recording(project: Project): Recording {
  const scenes = project.script?.scenes ?? [];
  const recorded = scenes.filter((s) => s.take).length;
  const video = project.clips.length > 0;
  return {
    takes: scenes.length,
    recorded,
    video,
    complete: video || (scenes.length > 0 && recorded === scenes.length),
  };
}

function done(project: Project, id: StepId): boolean {
  switch (id) {
    case "write":
    case "check":
      return Boolean(project.story);
    case "record":
      return recording(project).complete;
    case "transcribe":
      return Boolean(project.transcript);
    case "draw":
      return Boolean(project.part_pictures && project.analysis);
    case "render":
      return project.renders.length > 0;
  }
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** What the storyboard check made of the part, in a few words. */
export function checkOutcome(story: Story): string {
  if (story.problems.length) return `${plural(story.problems.length, "note")} left to look at`;
  const fixed = story.review_found ?? 0;
  if (fixed) return `Fixed ${plural(fixed, "picture")} that didn't match the chapter`;
  return "Every picture matches the chapter";
}

/** The six steps, each done, running, failed, waiting for the user, or still to come. */
export function partSteps(project: Project): FlowStep[] {
  const job = project.job;
  const running = jobActive(project) ? jobStep(job) : null;
  const failed = !running && job?.status === "failed" ? jobStep(job) : null;
  const firstOpen = ORDER.find((id) => !done(project, id)) ?? null;
  const current = running ?? (failed && !done(project, failed) ? failed : firstOpen);
  const at = current ? ORDER.indexOf(current) : ORDER.length;
  const rec = recording(project);
  const story = project.story;

  return ORDER.map((id, index) => {
    let state: StepState;
    if (index < at) state = "done";
    else if (index > at) state = "todo";
    else if (id === running) state = "active";
    else if (id === failed) state = "failed";
    else if (id === "record") state = "yours";
    else state = "todo";

    let detail = "";
    if (id === "write") {
      if (state === "done" && story) {
        const chars = [story.hook, ...story.beats.map((b) => b.text), story.poll.text, story.cta].join(" ").length;
        detail = `${story.beats.length} beats · about ${Math.round(chars / 13.5)}s read aloud`;
      } else if (state === "active") detail = job?.step === "Writing the part" ? "Muse Spark is writing" : job?.step || "";
    } else if (id === "check") {
      if (state === "active") detail = job?.step?.startsWith("Fixing") ? "Fixing what the check found" : "Does every picture show what the words say?";
      else if (state === "done" && story) detail = checkOutcome(story);
    } else if (id === "record") {
      if (rec.video) detail = "One video of the whole part";
      else if (rec.takes) detail = `${rec.recorded} of ${rec.takes} takes recorded`;
    } else if (id === "transcribe") {
      if (state === "done" && project.transcript) detail = `${project.transcript.turns.length} lines heard`;
      else if (state === "active") detail = job?.step === "Transcribing" ? "Muse Voice Transcribe is listening" : "Preparing your recording";
    } else if (id === "draw") {
      const pictures = Object.values(project.part_pictures || {});
      if (state === "done") {
        const broken = pictures.filter((p) => p.error).length;
        detail = `${pictures.length} pictures${broken ? `, ${broken} failed` : ""}`;
      } else if (state === "active") detail = "Muse Image draws them, SAM cuts them out";
    } else if (id === "render") {
      const last = project.renders[project.renders.length - 1];
      if (state === "done" && last) detail = "Ready to download";
      else if (state === "active") detail = "Captions, pictures and your voice, put together";
    }
    if (state === "failed" && job?.error) detail = job.error;
    return { id, label: STEP_LABELS[id], state, detail };
  });
}
