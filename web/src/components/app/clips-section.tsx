import { useRef, useState } from "react";
import { ArrowUp, ArrowDown, X, UploadCloud, Loader2 } from "lucide-react";
import { api, mediaUrl, upload } from "@/lib/api";
import type { Project } from "@/lib/types";
import { useConfig } from "@/lib/config";
import { useToast } from "@/lib/toast";
import { megabytes, seconds } from "@/lib/format";
import { Card } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import type { UseProjectState } from "./project-view";

export function ClipsSection({ project, state }: { project: Project; state: UseProjectState }) {
  const config = useConfig();
  const { toast } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<{ name: string; value: number }[]>([]);

  const move = (index: number, delta: number) => {
    const ids = project.clips.map((c) => c.id);
    const [moved] = ids.splice(index, 1);
    ids.splice(index + delta, 0, moved);
    state.act(() => api.orderClips(project.id, ids));
  };

  const uploadClips = async (files: File[]) => {
    if (!files.length) return;
    for (const file of files) {
      setProgress((p) => [...p, { name: file.name, value: 0 }]);
      try {
        const updated = await upload(
          `/api/projects/${project.id}/clips`,
          file,
          file.name,
          (f) => setProgress((p) => p.map((x) => (x.name === file.name ? { ...x, value: f } : x))),
        );
        state.set(updated);
        toast(`Added ${file.name}`, "ok");
      } catch (e) {
        toast(`${file.name}: ${e instanceof Error ? e.message : e}`, "error");
      } finally {
        setProgress((p) => p.filter((x) => x.name !== file.name));
      }
    }
  };

  const uploading = progress.length > 0;

  return (
    <Card title="Your video">
      {project.clips.length ? (
        <ol className="mb-4 flex flex-col gap-3">
          {project.clips.map((clip, index) => (
            <li
              key={clip.id}
              className="flex items-center gap-3 rounded-2xl border border-border bg-background p-2.5"
            >
              <video
                src={mediaUrl(project.id, clip.key)}
                preload="metadata"
                muted
                playsInline
                controls
                className="h-20 w-14 shrink-0 rounded-lg object-cover"
              />
              <div className="flex min-w-0 flex-1 flex-col">
                <strong className="truncate text-sm">{clip.name}</strong>
                <small className="text-xs text-muted-foreground">
                  {seconds(clip.duration)} · {clip.width}×{clip.height} · {Math.round(clip.fps)} fps
                  {clip.has_audio ? "" : " · no sound"}
                  {clip.hdr ? " · HDR" : ""} · {megabytes(clip.size)}
                </small>
              </div>
              <div className="flex items-center gap-1">
                <IconBtn title="Move up" disabled={index === 0} onClick={() => move(index, -1)}>
                  <ArrowUp className="size-4" />
                </IconBtn>
                <IconBtn
                  title="Move down"
                  disabled={index === project.clips.length - 1}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown className="size-4" />
                </IconBtn>
                <IconBtn
                  title="Remove"
                  onClick={() => {
                    if (confirm(`Remove ${clip.name}?`))
                      state.act(() => api.deleteClip(project.id, clip.id));
                  }}
                >
                  <X className="size-4" />
                </IconBtn>
              </div>
            </li>
          ))}
        </ol>
      ) : null}
      <p className="mb-3 text-xs text-muted-foreground">
        {project.clips.length
          ? `Total ${seconds(project.input_seconds)} of ${config.max_input_seconds}s.`
          : "Portrait (9:16) works best; other shapes are centre-cropped."}
      </p>
      <div
        role="button"
        tabIndex={uploading ? -1 : 0}
        aria-disabled={uploading}
        onClick={() => !uploading && fileInput.current?.click()}
        onKeyDown={(e) =>
          !uploading && (e.key === "Enter" || e.key === " ") && fileInput.current?.click()
        }
        onDragOver={(e) => {
          if (uploading) return;
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          if (uploading) return;
          e.preventDefault();
          setDragging(false);
          uploadClips(
            [...e.dataTransfer.files].filter(
              (f) => f.type.startsWith("video/") || /\.(mp4|mov|m4v|webm|mkv)$/i.test(f.name),
            ),
          );
        }}
        className={cn(
          "flex flex-col items-center gap-1.5 rounded-2xl border-2 border-dashed p-8 text-center transition-colors",
          uploading
            ? "cursor-not-allowed border-accent/40 bg-accent/5 opacity-70"
            : dragging
              ? "cursor-pointer border-accent bg-accent/5"
              : "cursor-pointer border-border-strong hover:border-accent/50",
        )}
      >
        {uploading ? (
          <>
            <Loader2 className="size-6 animate-spin text-accent" />
            <strong className="text-sm">Uploading…</strong>
            <small className="text-xs text-muted-foreground">Please wait for the upload to finish</small>
          </>
        ) : (
          <>
            <UploadCloud className="size-6 text-muted-foreground" />
            <strong className="text-sm">Drop video clips here, or click to choose</strong>
            <small className="text-xs text-muted-foreground">
              MP4, MOV or WebM · up to {config.max_input_seconds}s in total · clips play in this order
            </small>
          </>
        )}
      </div>
      {/* The input is a sibling, not a child, of the clickable dropzone: otherwise the file
          picker's click bubbles back into the dropzone's onClick and reopens the dialog. */}
      <input
        ref={fileInput}
        type="file"
        accept="video/*"
        multiple
        hidden
        onChange={(e) => {
          uploadClips([...(e.target.files ?? [])]);
          e.target.value = ""; // allow re-selecting the same file
        }}
      />
      {progress.map((p) => (
        <div key={p.name} className="mt-3 rounded-xl border border-accent/40 bg-accent/5 p-3">
          <div className="mb-1.5 flex items-center justify-between text-xs">
            <span className="truncate font-medium text-foreground">Uploading {p.name}…</span>
            <span className="shrink-0 text-muted-foreground">{Math.round(p.value * 100)}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-border-strong">
            <div
              className="h-full rounded-full transition-[width] duration-200"
              style={{ width: `${Math.round(p.value * 100)}%`, background: "var(--gradient-accent)" }}
            />
          </div>
        </div>
      ))}
    </Card>
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
