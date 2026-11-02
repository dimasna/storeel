import { useRef, useState } from "react";
import { X } from "lucide-react";
import { api, mediaUrl, novelMediaUrl, upload } from "@/lib/api";
import type { Beat, Project, ShowTags, Story } from "@/lib/types";
import { useConfig } from "@/lib/config";
import { labelFor } from "@/lib/labels";
import { useToast } from "@/lib/toast";
import { seconds } from "@/lib/format";
import { Card, Field, Input, Textarea, Pill, Banner } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { Recorder } from "./recorder";
import { HeardPill } from "./idea-section";
import type { UseProjectState } from "./project-view";

// ---- Part intro + write/from-video actions ------------------------------------------------

export function PartSection({ project, state }: { project: Project; state: UseProjectState }) {
  const config = useConfig();
  const part = project.novel;
  const story = project.story;
  const video = project.clips[0];
  const fromVideo = Boolean(story?.from_video);
  const writer = config.models.script_name;
  const fileInput = useRef<HTMLInputElement>(null);

  const write = async () => {
    const takes = project.script ? project.script.scenes.filter((s) => s.take).length : 0;
    if (takes && !confirm(`A new script replaces this one and deletes ${takes} recorded take(s). Continue?`))
      return;
    if (video && !confirm("A new script won't match the uploaded video, so the video is removed and you record the new script. Continue?"))
      return;
    if (video && !(await state.act(() => api.deleteClip(project.id, video.id)))) return;
    state.act(() => api.writePart(project.id, false), `${writer} is writing the part…`);
  };

  const fromMyVideo = () =>
    state.act(() => api.writePart(project.id, true), "Making the part from your video…");

  let about: string;
  let actions: React.ReactNode;
  if (!story) {
    about = video
      ? `Your video (${seconds(video.duration)}) is uploaded. ${writer} makes the part from it: what you said, split into beats, with pictures planned for each one.`
      : `${writer} writes the part from the chapter and the character bible: the hook, the story beats, a poll and the call to action. You then record it. Already recorded it? Upload your video instead.`;
    actions = video ? (
      <>
        <Button variant="primary" onClick={fromMyVideo}>
          Make the part from this video
        </Button>
        <Button onClick={() => confirm("Remove this video?") && state.act(() => api.deleteClip(project.id, video.id))}>
          Remove the video
        </Button>
      </>
    ) : (
      <>
        <Button variant="primary" onClick={write}>
          Write the part
        </Button>
        <Button onClick={() => fileInput.current?.click()}>Make it from my video</Button>
      </>
    );
  } else if (fromVideo) {
    about = "Made from your video: the beats are what you said, and the pictures are planned for them. Make it again if the pictures miss something.";
    actions = (
      <>
        <Button variant="primary" onClick={fromMyVideo}>
          Make it again from the video
        </Button>
        <Button onClick={write}>Write a script from the chapter instead</Button>
      </>
    );
  } else {
    about = "Rewrite the part if it misses the chapter's best moments. Edit single words below instead — that keeps your takes.";
    actions = (
      <>
        <Button variant="primary" onClick={write}>
          Rewrite the part
        </Button>
        {video ? <Button onClick={fromMyVideo}>Make the part from my video instead</Button> : null}
      </>
    );
  }

  return (
    <Card title={story ? undefined : `Part ${project.chapter}`}>
      {part ? (
        <details className="mb-3">
          <summary className="cursor-pointer text-sm">
            <strong>
              Chapter {project.chapter}
              {part.chapter_title ? `: ${part.chapter_title}` : ""}
            </strong>
            <span className="text-muted-foreground"> · {part.chapter_text.length.toLocaleString()} chars</span>
          </summary>
          <div className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-xl bg-background p-3 text-sm text-muted-foreground">
            {part.chapter_text}
          </div>
        </details>
      ) : (
        <Banner tone="warn">This reel's novel was deleted.</Banner>
      )}
      <p className="mb-3 text-sm text-muted-foreground">{about}</p>
      {part ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      <input
        ref={fileInput}
        type="file"
        accept="video/*"
        hidden
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          const added = await state.act(
            () => upload(`/api/projects/${project.id}/clips`, file, file.name),
            "Video added",
          );
          if (added) state.act(() => api.writePart(project.id, true), "Making the part from your video…");
        }}
      />
    </Card>
  );
}

// ---- Story (beats) editing ----------------------------------------------------------------

function ShowTagsRow({ show, prefix }: { show?: ShowTags; prefix?: string }) {
  if (!show) return null;
  const tags: string[] = [];
  (show.characters || []).forEach((c) => tags.push(c));
  if (show.prop) tags.push(`object: ${show.prop}`);
  if (show.photo) tags.push(`photo: ${show.photo}`);
  (show.chat || []).forEach((m) => tags.push(`chat ${m.sender}: ${m.text}`));
  if (show.note?.text) tags.push(`note: ${show.note.text}`);
  if (show.tag) tags.push(show.tag);
  if (!tags.length) return null;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      {prefix ? <span className="text-xs text-muted-foreground">{prefix}</span> : null}
      {tags.map((t, i) => (
        <span key={i} className="rounded-md bg-card px-1.5 py-0.5 text-xs text-muted-foreground">
          {t}
        </span>
      ))}
    </div>
  );
}

export function StorySection({ project, state }: { project: Project; state: UseProjectState }) {
  const [story, setStory] = useState<Story>(() => structuredClone(project.story!));
  const [dirty, setDirty] = useState(false);
  const said = Boolean(story.from_video);

  const mutate = (fn: (s: Story) => void) => {
    setStory((prev) => {
      const next = structuredClone(prev);
      fn(next);
      return next;
    });
    setDirty(true);
  };

  const save = () =>
    state
      .act(
        () =>
          api.editPart(project.id, {
            chapter_title: story.chapter_title,
            hook: story.hook,
            hook_direction: story.hook_direction,
            beats: story.beats.map((b) => ({ text: b.text, direction: b.direction })),
            poll: story.poll,
            cta: story.cta,
          }),
        said ? "Saved" : "Saved. Re-record any take whose words you changed.",
      )
      .then((p: Project | null) => {
        if (p) {
          setStory(structuredClone(p.story!));
          setDirty(false);
        }
      });

  const chars = [story.hook, ...story.beats.map((b) => b.text), story.poll.text, story.cta].join(" ").length;

  const Words = ({ value, onChange, maxLength = 400 }: { value: string; onChange: (v: string) => void; maxLength?: number }) =>
    said ? (
      <p className="whitespace-pre-wrap text-sm text-foreground">{value}</p>
    ) : (
      <Textarea rows={Math.max(2, Math.ceil(value.length / 70))} maxLength={maxLength} value={value} onChange={(e) => onChange(e.target.value)} />
    );

  const Note = ({ value, onChange }: { value: string; onChange: (v: string) => void }) =>
    said ? null : (
      <Input className="mt-1" value={value} maxLength={200} placeholder="delivery note" onChange={(e) => onChange(e.target.value)} />
    );

  return (
    <Card title="Part script">
      <p className="mb-3 text-xs text-muted-foreground">
        {said
          ? `Part ${story.part} · ${story.beats.length} beats, in your own words from the video.`
          : `Part ${story.part} · ${story.beats.length} beats · ${chars.toLocaleString()} characters, about ${Math.round(chars / 13.5)}s read aloud.`}
      </p>
      {story.problems.length ? (
        <Banner tone="warn" className="mb-3">
          <strong>Still to fix: </strong>
          {story.problems.join("; ")}
        </Banner>
      ) : null}
      {!said ? (
        <Field label="Part title" className="mb-3">
          <Input value={story.chapter_title} maxLength={120} onChange={(e) => mutate((s) => (s.chapter_title = e.target.value))} />
        </Field>
      ) : null}

      <ol className="flex flex-col gap-3">
        <li className="rounded-2xl border border-accent/30 bg-background p-3">
          <div className="mb-1 text-xs text-muted-foreground">
            Hook · on camera{said ? " · what you say first" : " · take 1"}
            {!said && project.novel?.opening ? ` · starts with “${project.novel.opening}…”` : ""}
          </div>
          <Words value={story.hook} onChange={(v) => mutate((s) => (s.hook = v))} />
          <Note value={story.hook_direction} onChange={(v) => mutate((s) => (s.hook_direction = v))} />
        </li>

        {story.beats.map((b: Beat, i) => (
          <li key={i} className="rounded-2xl border border-border bg-background p-3">
            <div className="mb-1 text-xs text-muted-foreground">
              Beat {i + 1} · {labelFor("act", b.act)}
              {said ? "" : ` · take ${b.take.slice(1)}`}
              {b.speaker !== "narrator" ? ` · quoting ${b.speaker}` : ""}
            </div>
            <Words value={b.text} onChange={(v) => mutate((s) => (s.beats[i].text = v))} />
            <Note value={b.direction} onChange={(v) => mutate((s) => (s.beats[i].direction = v))} />
            <ShowTagsRow show={b.show} />
            {b.switch ? <ShowTagsRow show={b.switch.show} prefix={`at “${b.switch.at}” →`} /> : null}
          </li>
        ))}

        {said && !story.poll.text ? null : (
          <li className="rounded-2xl border border-border bg-background p-3">
            <div className="mb-1 text-xs text-muted-foreground">Poll · two options on screen</div>
            <Words value={story.poll.text} onChange={(v) => mutate((s) => (s.poll.text = v))} />
            <div className="mt-2 grid grid-cols-2 gap-2">
              <Field label="Option A">
                <Input value={story.poll.a} maxLength={40} onChange={(e) => mutate((s) => (s.poll.a = e.target.value))} />
              </Field>
              <Field label="Option B">
                <Input value={story.poll.b} maxLength={40} onChange={(e) => mutate((s) => (s.poll.b = e.target.value))} />
              </Field>
            </div>
          </li>
        )}

        {said && !story.cta ? null : (
          <li className="rounded-2xl border border-border bg-background p-3">
            <div className="mb-1 text-xs text-muted-foreground">Call to action · over the end card</div>
            <Words value={story.cta} onChange={(v) => mutate((s) => (s.cta = v))} />
          </li>
        )}
      </ol>

      <div className="mt-4">
        <Button variant="primary" disabled={!dirty} onClick={save}>
          {said ? "Save" : "Save the words"}
        </Button>
      </div>
      {said && !story.poll.text && !story.cta ? (
        <p className="mt-2 text-xs text-muted-foreground">
          You didn't end with a poll or a call to action, so the reel has no poll screen or end card.
        </p>
      ) : null}
    </Card>
  );
}

// ---- Takes (recording a part) -------------------------------------------------------------

export function TakesSection({ project, state }: { project: Project; state: UseProjectState }) {
  const { toast } = useToast();
  const scenes = project.script?.scenes ?? [];
  const recorded = scenes.filter((s) => s.take).length;
  const whole = project.clips[0];
  const said = Boolean(project.story?.from_video);
  const [recording, setRecording] = useState<number | null>(null);
  const wholeInput = useRef<HTMLInputElement>(null);

  return (
    <Card title={said ? "Your video" : "Record the part"}>
      <p className="mb-3 text-sm text-muted-foreground">
        {whole
          ? said
            ? "The part was made from this video: its beats are what you said. Removing it leaves the beats to record as takes."
            : "This video is used instead of the takes. Its words are matched to the script to time the pictures."
          : `${scenes.length} takes · ${recorded} recorded: the hook, one per beat, the poll and the call to action. Each take is a few lines, read from the teleprompter in one go.`}
      </p>

      {whole ? (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <video src={mediaUrl(project.id, whole.key)} controls playsInline preload="metadata" className="h-24 rounded-lg" />
          <Pill tone="ok">one video · {seconds(whole.duration)}</Pill>
          <button
            title="Remove the video"
            onClick={() =>
              confirm("Remove this video? The takes (if any) are used again.") &&
              state.act(() => api.deleteClip(project.id, whole.id))
            }
            className="grid size-8 place-items-center rounded-lg border border-border-strong text-muted-foreground hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>
      ) : (
        <div className="mb-3">
          <Button size="sm" onClick={() => wholeInput.current?.click()}>
            Upload one video of the whole part
          </Button>
          <input
            ref={wholeInput}
            type="file"
            accept="video/*"
            hidden
            onChange={(e) =>
              e.target.files?.[0] &&
              state.act(
                () => upload(`/api/projects/${project.id}/clips`, e.target.files![0], e.target.files![0].name),
                "Video added",
              )
            }
          />
        </div>
      )}

      <HeardBanner project={project} />

      {!whole ? (
        <ol className="flex flex-col gap-3">
          {scenes.map((scene, index) => (
            <li key={scene.id} className="rounded-2xl border border-border bg-background p-3">
              <div className="mb-2 flex items-center gap-2">
                <span className="grid size-6 place-items-center rounded-md bg-card text-xs font-semibold">
                  {index + 1}
                </span>
                <span className="flex-1 text-xs text-muted-foreground">{scene.purpose}</span>
                <HeardPill project={project} sceneId={scene.id} hasTake={Boolean(scene.take)} />
              </div>
              <p className="mb-1 text-sm">{scene.lines}</p>
              {scene.direction ? <p className="mb-2 text-xs text-muted-foreground">{scene.direction}</p> : null}
              {scene.take ? (
                <div className="flex flex-wrap items-center gap-2">
                  <video src={mediaUrl(project.id, scene.take.key)} controls playsInline preload="metadata" className="h-20 rounded-lg" />
                  <Pill tone="ok">recorded · {seconds(scene.take.duration)}</Pill>
                  <Button size="sm" onClick={() => setRecording(index)}>
                    Retake
                  </Button>
                  <button
                    title="Delete take"
                    onClick={() => confirm("Delete this take?") && state.act(() => api.deleteTake(project.id, scene.id))}
                    className="grid size-8 place-items-center rounded-lg border border-border-strong text-muted-foreground hover:text-foreground"
                  >
                    <X className="size-4" />
                  </button>
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="primary" onClick={() => setRecording(index)}>
                    ● Record
                  </Button>
                  <TakeUpload project={project} sceneId={scene.id} index={index} state={state} />
                </div>
              )}
            </li>
          ))}
        </ol>
      ) : null}

      {recording !== null ? (
        <Recorder
          scene={scenes[recording]}
          index={recording}
          total={scenes.length}
          onTake={async (blob, name, onProgress) => {
            const updated = await upload(
              `/api/projects/${project.id}/scenes/${scenes[recording].id}/take`,
              blob,
              name,
              onProgress,
            );
            state.set(updated);
            toast(`Take ${recording + 1} recorded`, "ok");
          }}
          onClose={() => setRecording(null)}
        />
      ) : null}
    </Card>
  );
}

function TakeUpload({
  project,
  sceneId,
  index,
  state,
}: {
  project: Project;
  sceneId: string;
  index: number;
  state: UseProjectState;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <>
      <Button size="sm" onClick={() => ref.current?.click()}>
        Upload a take
      </Button>
      <input
        ref={ref}
        type="file"
        accept="video/*"
        hidden
        onChange={(e) =>
          e.target.files?.[0] &&
          state.act(
            () => upload(`/api/projects/${project.id}/scenes/${sceneId}/take`, e.target.files![0], e.target.files![0].name),
            `Take ${index + 1} added`,
          )
        }
      />
    </>
  );
}

export function HeardBanner({ project }: { project: Project }) {
  const heard = project.heard || {};
  const scenes = project.script?.scenes ?? [];
  const checked = scenes.filter((s) => heard[s.id]);
  const off = checked.filter((s) => heard[s.id].status === "not heard");
  if (!off.length) return null;
  const first = (s: (typeof scenes)[number]) =>
    `${scenes.indexOf(s) + 1}. “${s.lines.split(/\s+/).slice(0, 5).join(" ")}…”`;
  return (
    <Banner tone="warn" className="mb-3">
      <strong>{off.length} of {checked.length} lines don't match what you said. </strong>
      Re-record these takes, or their pictures won't fit what you say: {off.map(first).join("  ")}
    </Banner>
  );
}

// ---- Part process + pictures --------------------------------------------------------------

export function PartProcessSection({ project, state }: { project: Project; state: UseProjectState }) {
  const processed = Boolean(project.part_pictures);
  return (
    <Card title={processed ? "Pictures" : "Process"}>
      <p className="mb-3 text-sm text-muted-foreground">
        {processed
          ? "Update after a retake or a script change: only what changed is made again."
          : "Transcribes your recording, then draws the part's pictures with Muse Image: characters from the bible (cut out by SAM), objects, places and photos."}
      </p>
      <Button
        variant="primary"
        onClick={() =>
          state.act(() => api.process(project.id, false), processed ? "Updating…" : "Processing started")
        }
      >
        {processed ? "Update" : "Process the part"}
      </Button>
    </Card>
  );
}

export function PartPicturesSection({ project }: { project: Project }) {
  const pictures = Object.values(project.part_pictures || {});
  const how: Record<string, string> = {
    standing: "stands at the bottom",
    object: "cut-out object",
    scene: "cut-out scene",
    card: "card",
  };
  const url = (p: (typeof pictures)[number]) =>
    p.scope === "novel" && project.novel ? novelMediaUrl(project.novel.id, p.key!) : mediaUrl(project.id, p.key!);

  return (
    <Card title="The part's pictures">
      <p className="mb-3 text-sm text-muted-foreground">
        Characters come from the novel's bible; a returning character is redrawn in this part's
        outfit from their earlier portrait.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {pictures.map((p) => (
          <div key={p.id} className="flex flex-col gap-2 rounded-2xl border border-border bg-background p-2">
            {p.key ? (
              <a href={url(p)} target="_blank" rel="noopener noreferrer">
                <img src={url(p)} alt={p.id} loading="lazy" className="w-full rounded-lg object-cover" />
              </a>
            ) : (
              <div className="grid aspect-square w-full place-items-center rounded-lg bg-card text-muted-foreground">
                !
              </div>
            )}
            <div>
              <strong className="block text-sm">{p.id}</strong>
              <small className="text-xs text-muted-foreground">
                {p.kind} · {how[p.display] || p.display}
              </small>
              {p.checked && !p.problems.length ? (
                <p className="text-xs text-success">✓ checked</p>
              ) : null}
              {p.checked && p.problems.length ? (
                <p className="text-xs text-warning">Still: {p.problems.join("; ")}</p>
              ) : null}
              {p.error ? <p className="text-xs text-danger">{p.error}</p> : null}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
