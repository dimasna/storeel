import { useRef, useState } from "react";
import { ArrowUp, ArrowDown, X } from "lucide-react";
import { api, upload } from "@/lib/api";
import type { Project, Scene, Script } from "@/lib/types";
import { useConfig } from "@/lib/config";
import { enumOf, labelFor } from "@/lib/labels";
import { useToast } from "@/lib/toast";
import { Card, Field, Input, Textarea, Select, Pill } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { Recorder } from "./recorder";
import { mediaUrl } from "@/lib/api";
import { seconds } from "@/lib/format";
import type { UseProjectState } from "./project-view";

/** A target length, whole seconds: "45s", "1 min 30s", "5 min". */
function clock(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (!m) return `${s}s`;
  return s ? `${m} min ${s}s` : `${m} min`;
}

export function IdeaSection({ project, state }: { project: Project; state: UseProjectState }) {
  const config = useConfig();
  const { toast } = useToast();
  const idea = project.idea ?? { text: "", format: "storytime", tone: "casual", length: 30, language: "id" };
  const [text, setText] = useState(idea.text);
  const [format, setFormat] = useState(idea.format);
  const [tone, setTone] = useState(idea.tone);
  const [language, setLanguage] = useState(idea.language);
  const [length, setLength] = useState(idea.length);

  const write = () => {
    if (text.trim().length < 3) return toast("Describe the idea first", "error");
    const takes = project.script ? project.script.scenes.filter((s) => s.take).length : 0;
    if (takes && !confirm(`A new script replaces the current one and deletes ${takes} recorded take(s). Continue?`))
      return;
    state.act(
      () => api.setIdea(project.id, { text: text.trim(), format, tone, length, language }),
      `${config.models.script_name} is writing the script…`,
    );
  };

  return (
    <Card title={project.script ? undefined : "Your idea"}>
      <div className="flex flex-col gap-3">
        <Field label="Idea or topic">
          <Textarea
            rows={4}
            maxLength={2000}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="What is the reel about? A story, a tip, an opinion…"
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Format">
            <Select value={format} onChange={(e) => setFormat(e.target.value)}>
              {enumOf(config.idea, "format").map((v) => (
                <option key={v} value={v}>
                  {labelFor("format", v)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Tone">
            <Select value={tone} onChange={(e) => setTone(e.target.value)}>
              {enumOf(config.idea, "tone").map((v) => (
                <option key={v} value={v}>
                  {labelFor("tone", v)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Language">
            <Select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {["id", "en"].map((v) => (
                <option key={v} value={v}>
                  {labelFor("idea_language", v)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label={`Length — ${clock(length)}`}>
          <input
            type="range"
            min={15}
            max={300}
            step={length < 60 ? 5 : 15}
            value={length}
            onChange={(e) => setLength(Number(e.target.value))}
            className="w-full accent-accent"
          />
        </Field>
        <div>
          <Button variant="primary" onClick={write}>
            {project.script ? "Write a new script" : "Write the script"}
          </Button>
        </div>
      </div>
    </Card>
  );
}

// ---- Script with scene editing + recording ------------------------------------------------

export function ScriptSection({ project, state }: { project: Project; state: UseProjectState }) {
  const { toast } = useToast();
  const [script, setScript] = useState<Script>(() => structuredClone(project.script!));
  const [dirty, setDirty] = useState(false);
  const [recording, setRecording] = useState<number | null>(null);

  const markDirty = () => setDirty(true);
  const mutate = (fn: (s: Script) => void) => {
    setScript((prev) => {
      const next = structuredClone(prev);
      fn(next);
      return next;
    });
    markDirty();
  };

  const save = () =>
    state
      .act(
        () =>
          api.setScript(project.id, {
            title: script.title.trim() || "Untitled",
            language: script.language,
            entities: script.entities,
            scenes: script.scenes.map(({ take: _take, ...scene }) => {
              void _take;
              return scene;
            }),
          }),
        "Script saved",
      )
      .then((p: Project | null) => {
        if (p) {
          setScript(structuredClone(p.script!));
          setDirty(false);
        }
      });

  const recorded = script.scenes.filter((s) => s.take).length;
  const words = script.scenes.reduce((n, s) => n + s.lines.split(/\s+/).length, 0);

  const addScene = () =>
    mutate((s) => {
      const used = new Set(s.scenes.map((x) => x.id));
      let n = s.scenes.length + 1;
      while (used.has(`s${n}`)) n += 1;
      s.scenes.push({
        id: `s${n}`,
        purpose: "story",
        lines: "…",
        direction: "",
        display: "none",
        visual: "",
        entities: [],
        take: null,
      });
    });

  return (
    <Card title={project.analysis ? undefined : "Script"}>
      <p className="mb-3 text-xs text-muted-foreground">
        {script.scenes.length} scenes · {recorded} recorded · about {words} words. Record each scene
        in one take; edit the lines first if they don't sound like you.
      </p>
      <Field label="Title" className="mb-3">
        <Input value={script.title} maxLength={120} onChange={(e) => mutate((s) => (s.title = e.target.value))} />
      </Field>
      <ol className="flex flex-col gap-3">
        {script.scenes.map((scene, index) => (
          <SceneCard
            key={scene.id}
            project={project}
            script={script}
            scene={scene}
            index={index}
            state={state}
            dirty={dirty}
            mutate={mutate}
            onRecord={() => {
              if (dirty) return toast("Save the script before recording", "error");
              setRecording(index);
            }}
          />
        ))}
      </ol>
      <div className="mt-4 flex gap-2">
        <Button size="sm" onClick={addScene}>
          + Add scene
        </Button>
        <Button size="sm" variant="primary" disabled={!dirty} onClick={save}>
          Save script
        </Button>
      </div>

      {recording !== null ? (
        <Recorder
          scene={script.scenes[recording]}
          index={recording}
          total={script.scenes.length}
          onTake={async (blob, name, onProgress) => {
            const updated = await upload(
              `/api/projects/${project.id}/scenes/${script.scenes[recording].id}/take`,
              blob,
              name,
              onProgress,
            );
            state.set(updated);
            setScript(structuredClone(updated.script!));
            toast(`Scene ${recording + 1} recorded`, "ok");
          }}
          onClose={() => setRecording(null)}
        />
      ) : null}
    </Card>
  );
}

function SceneCard({
  project,
  script,
  scene,
  index,
  state,
  dirty,
  mutate,
  onRecord,
}: {
  project: Project;
  script: Script;
  scene: Scene;
  index: number;
  state: UseProjectState;
  dirty: boolean;
  mutate: (fn: (s: Script) => void) => void;
  onRecord: () => void;
}) {
  const { toast } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);

  const move = (delta: number) =>
    mutate((s) => {
      const [item] = s.scenes.splice(index, 1);
      s.scenes.splice(index + delta, 0, item);
    });

  const remove = () => {
    if (scene.take && !confirm("This scene has a recorded take. Delete the scene and its take when you save?"))
      return;
    mutate((s) => s.scenes.splice(index, 1));
  };

  const uploadTake = async (file: File) => {
    if (dirty) return toast("Save the script before adding takes", "error");
    await state.act(
      () => upload(`/api/projects/${project.id}/scenes/${scene.id}/take`, file, file.name),
      `Scene ${index + 1}: take added`,
    );
  };

  return (
    <li className="rounded-2xl border border-border bg-background p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="grid size-6 place-items-center rounded-md bg-card text-xs font-semibold">
          {index + 1}
        </span>
        <span className="flex-1 text-xs text-muted-foreground">{scene.purpose}</span>
        <HeardPill project={project} sceneId={scene.id} hasTake={Boolean(scene.take)} />
        <IconBtn title="Move up" disabled={index === 0} onClick={() => move(-1)}>
          <ArrowUp className="size-4" />
        </IconBtn>
        <IconBtn title="Move down" disabled={index === script.scenes.length - 1} onClick={() => move(1)}>
          <ArrowDown className="size-4" />
        </IconBtn>
        <IconBtn title="Delete scene" disabled={script.scenes.length === 1} onClick={remove}>
          <X className="size-4" />
        </IconBtn>
      </div>
      <Field label="Lines" className="mb-2">
        <Textarea
          rows={2}
          maxLength={600}
          value={scene.lines}
          onChange={(e) => mutate((s) => (s.scenes[index].lines = e.target.value))}
        />
      </Field>
      <div className="mb-2 grid grid-cols-2 gap-2">
        <Field label="Delivery">
          <Input
            value={scene.direction}
            maxLength={300}
            placeholder="delivery note"
            onChange={(e) => mutate((s) => (s.scenes[index].direction = e.target.value))}
          />
        </Field>
        <Field label="While spoken">
          <Select
            value={scene.display}
            onChange={(e) =>
              mutate((s) => {
                s.scenes[index].display = e.target.value;
                if (e.target.value === "none") s.scenes[index].visual = "";
              })
            }
          >
            {["none", "overlay", "cutout", "cutaway"].map((v) => (
              <option key={v} value={v}>
                {labelFor("display", v)}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {scene.display !== "none" ? (
        <Field label="Picture" className="mb-2">
          <Textarea
            rows={2}
            maxLength={800}
            value={scene.visual}
            placeholder="English: the picture shown while this scene is spoken"
            onChange={(e) => mutate((s) => (s.scenes[index].visual = e.target.value))}
          />
        </Field>
      ) : null}

      {scene.take ? (
        <div className="flex flex-wrap items-center gap-2">
          <video
            src={mediaUrl(project.id, scene.take.key)}
            controls
            playsInline
            preload="metadata"
            className="h-20 rounded-lg"
          />
          <Pill tone="ok">recorded · {seconds(scene.take.duration)}</Pill>
          <Button size="sm" onClick={onRecord}>
            Retake
          </Button>
          <IconBtn
            title="Delete take"
            onClick={() => {
              if (confirm("Delete this take?"))
                state.act(() => api.deleteTake(project.id, scene.id));
            }}
          >
            <X className="size-4" />
          </IconBtn>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="primary" onClick={onRecord}>
            ● Record
          </Button>
          <Button size="sm" onClick={() => fileInput.current?.click()}>
            Upload a take
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept="video/*"
            hidden
            onChange={(e) => e.target.files?.[0] && uploadTake(e.target.files[0])}
          />
        </div>
      )}
    </li>
  );
}

export function HeardPill({
  project,
  sceneId,
  hasTake,
}: {
  project: Project;
  sceneId: string;
  hasTake: boolean;
}) {
  const heard = project.heard?.[sceneId];
  if (!hasTake || !heard || heard.status === "ok") return null;
  const title = `${Math.round(heard.share * 100)}% of the lines heard in this take`;
  return heard.status === "not heard" ? (
    <Pill tone="bad" title={title}>
      not heard
    </Pill>
  ) : (
    <Pill tone="warn" title={title}>
      partly heard
    </Pill>
  );
}

function IconBtn({
  children,
  title,
  disabled,
  onClick,
}: {
  children: React.ReactNode;
  title: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      title={title}
      disabled={disabled}
      onClick={onClick}
      className="grid size-8 place-items-center rounded-lg border border-border-strong text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
    >
      {children}
    </button>
  );
}
