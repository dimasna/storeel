import { Download, Sparkles } from "lucide-react";
import { mediaUrl } from "@/lib/api";
import type { Project } from "@/lib/types";
import { Link } from "@/lib/router";
import { megabytes, seconds } from "@/lib/format";
import { Card } from "@/components/ui/primitives";
import { PartPicturesSection } from "./novel-part-sections";

/** A showcase reel: anyone may watch it and download it; nobody may change it. */
export function ShowcaseView({ project }: { project: Project }) {
  const render = project.renders[project.renders.length - 1];
  const story = project.story;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <Link
          to={project.novel ? `/n/${project.novel.id}` : "/"}
          className="w-fit text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          {project.novel ? `← ${project.novel.title}` : "← Home"}
        </Link>
        <h1 className="font-display text-[2.4rem] leading-none tracking-[-0.01em]">{project.title}</h1>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-accent/40 bg-accent/5 px-4 py-3 text-sm">
        <Sparkles className="size-4 shrink-0 text-accent" />
        <span className="flex-1 text-foreground">
          A showcase reel: watch it and download it. Start your own from the home page.
        </span>
        <Link to="/" className="font-semibold text-accent hover:underline">
          Make your own
        </Link>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)] lg:items-start">
        <Card>
          {render ? (
            <div className="flex flex-col gap-3">
              <video
                src={mediaUrl(project.id, render.key)}
                controls
                playsInline
                preload="metadata"
                className="mx-auto max-h-[70dvh] w-full rounded-2xl border border-border bg-black object-contain"
              />
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="text-muted-foreground">
                  {seconds(render.duration)} · {megabytes(render.size)}
                </span>
                <a
                  href={mediaUrl(project.id, render.key, true)}
                  className="inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-border-strong px-4 text-sm font-semibold transition-colors hover:border-accent/60"
                >
                  <Download className="size-4" /> Download
                </a>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">This reel has not been rendered yet.</p>
          )}
        </Card>

        <div className="flex flex-col gap-5">
          {story ? (
            <Card title={`Part ${story.part}: ${story.chapter_title}`}>
              <ol className="flex flex-col gap-2 text-sm">
                <li className="rounded-xl border border-accent/30 bg-background p-3">
                  <span className="mb-1 block text-xs text-muted-foreground">Hook</span>
                  {story.hook}
                </li>
                {story.beats.map((beat, i) => (
                  <li key={i} className="rounded-xl border border-border bg-background p-3">
                    <span className="mb-1 block text-xs text-muted-foreground">Beat {i + 1}</span>
                    {beat.text}
                  </li>
                ))}
              </ol>
            </Card>
          ) : null}
          {project.part_pictures ? <PartPicturesSection project={project} /> : null}
        </div>
      </div>
    </div>
  );
}
