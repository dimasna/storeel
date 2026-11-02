import { useEffect, useState } from "react";
import { BookText, Film, Lightbulb, Play, Plus, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { api, mediaUrl } from "@/lib/api";
import type { NovelSummary, ProjectSummary } from "@/lib/types";
import { useToast } from "@/lib/toast";
import { navigate, Link } from "@/lib/router";
import { ago, seconds } from "@/lib/format";
import { Card, Banner } from "@/components/ui/primitives";
import { NewNovelDialog } from "@/components/app/new-novel-dialog";
import { ChapterComposer } from "@/components/app/chapter-composer";
import { EASE_OUT } from "@/lib/ease";

const PATH_LABEL: Record<string, string> = {
  idea: "From an idea",
  novel: "Novel part",
  video: "From a video",
};

export function HomePage() {
  const { toast } = useToast();
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [novels, setNovels] = useState<NovelSummary[] | null>(null);
  const [novelOpen, setNovelOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listProjects().then(setProjects).catch((e) => setError(String(e.message || e)));
    api.listNovels().then(setNovels).catch(() => setNovels([]));
  }, []);

  const create = async (path: "video" | "idea") => {
    try {
      const project = await api.createProject(path);
      navigate(`/p/${project.id}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const showcase = (projects ?? []).filter((p) => p.read_only);
  const mine = (projects ?? []).filter((p) => !p.read_only);
  const myNovels = (novels ?? []).filter((n) => !n.read_only);

  return (
    <div className="flex flex-col gap-8">
      <section className="mx-auto flex w-full max-w-3xl flex-col gap-5 pt-2 sm:pt-6">
        <div className="text-center">
          <motion.h1
            initial={{ opacity: 0, y: 12, filter: "blur(6px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            transition={{ duration: 0.5, ease: EASE_OUT }}
            className="text-3xl font-bold tracking-tight sm:text-4xl"
          >
            Turn a chapter into a <span className="gradient-text">reel</span>
          </motion.h1>
          <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            Paste a chapter of your novel. Muse Spark writes the part, you narrate it from a
            teleprompter, Muse Image draws the characters, and the reel is rendered for you.
          </p>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, delay: 0.05, ease: EASE_OUT }}
        >
          <ChapterComposer />
        </motion.div>

        <p className="text-center text-xs leading-relaxed text-muted-foreground">
          Your Muse / Model API key stays in this browser. Reels are kept for 24 hours: download
          yours before then.
        </p>
      </section>

      {showcase.length ? (
        <section className="flex flex-col gap-3">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <Sparkles className="size-4 text-accent" /> See one made with Storeel
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {showcase.map((p) => (
              <Link
                key={p.id}
                to={`/p/${p.id}`}
                className="group flex items-center gap-4 rounded-3xl border border-border bg-card/60 p-4 transition-colors hover:border-accent/50"
              >
                <span
                  className="grid size-14 shrink-0 place-items-center rounded-2xl text-white"
                  style={{ background: "var(--gradient-accent)" }}
                >
                  <Play className="size-6 fill-white" />
                </span>
                <span className="flex min-w-0 flex-col">
                  <strong className="truncate text-sm">{p.title}</strong>
                  <small className="text-xs text-muted-foreground">
                    {PATH_LABEL[p.path]}
                    {p.input_seconds ? ` · ${seconds(p.input_seconds)}` : ""} · watch and download
                  </small>
                </span>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      <Card title="Your reels">
        {error ? (
          <Banner tone="error">{error}</Banner>
        ) : projects === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : mine.length === 0 ? (
          <p className="text-sm text-muted-foreground">No reels yet. Paste a chapter above to make your first.</p>
        ) : (
          <div className="flex flex-col gap-1">
            {mine.map((p) => (
              <Link
                key={p.id}
                to={`/p/${p.id}`}
                className="flex items-center gap-3 rounded-xl border border-transparent p-2.5 transition-colors hover:border-border hover:bg-background"
              >
                {p.cover ? (
                  <img src={mediaUrl(p.id, p.cover)} alt="" className="h-14 w-10 shrink-0 rounded-md object-cover" />
                ) : (
                  <span className="grid h-14 w-10 shrink-0 place-items-center rounded-md bg-background text-muted-foreground">
                    {p.path === "idea" ? "✎" : p.path === "novel" ? "❡" : "▶"}
                  </span>
                )}
                <span className="flex min-w-0 flex-1 flex-col">
                  <strong className="truncate text-sm">{p.title}</strong>
                  <small className="text-xs text-muted-foreground">
                    {PATH_LABEL[p.path]} · {p.stage}
                    {p.input_seconds ? ` · ${seconds(p.input_seconds)}` : ""} · {ago(p.updated_at)}
                  </small>
                </span>
                {p.renders ? (
                  <span className="shrink-0 rounded-full border border-success/40 px-2.5 py-0.5 text-xs text-success">
                    {p.renders} render{p.renders > 1 ? "s" : ""}
                  </span>
                ) : null}
              </Link>
            ))}
          </div>
        )}
      </Card>

      <Card
        title="Your novels"
        actions={
          <button
            onClick={() => setNovelOpen(true)}
            className="inline-flex min-h-9 items-center gap-1 text-sm text-accent hover:underline"
          >
            <Plus className="size-4" /> New novel
          </button>
        }
      >
        {novels === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : myNovels.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            None yet. A novel keeps its characters the same from part to part.
          </p>
        ) : (
          <div className="flex flex-col gap-1">
            {myNovels.map((n) => (
              <Link
                key={n.id}
                to={`/n/${n.id}`}
                className="flex items-center gap-3 rounded-xl border border-transparent p-2.5 transition-colors hover:border-border hover:bg-background"
              >
                <span className="grid size-10 place-items-center rounded-lg bg-background text-muted-foreground">
                  <BookText className="size-4" />
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <strong className="truncate text-sm">{n.title}</strong>
                  <small className="text-xs text-muted-foreground">
                    {n.chapters} chapter{n.chapters === 1 ? "" : "s"} · {n.characters} character
                    {n.characters === 1 ? "" : "s"} · {ago(n.updated_at)}
                  </small>
                </span>
              </Link>
            ))}
          </div>
        )}
      </Card>

      <section className="flex flex-col items-center gap-3 border-t border-border pt-6 text-center">
        <p className="text-sm text-muted-foreground">Not a novel? Storeel also makes reels:</p>
        <div className="flex flex-wrap justify-center gap-2">
          <button
            onClick={() => create("video")}
            className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-border-strong px-4 text-sm font-semibold transition-colors hover:border-accent/60"
          >
            <Film className="size-4 text-accent" /> From your video
          </button>
          <button
            onClick={() => create("idea")}
            className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-border-strong px-4 text-sm font-semibold transition-colors hover:border-accent/60"
          >
            <Lightbulb className="size-4 text-accent" /> From an idea
          </button>
        </div>
      </section>

      <NewNovelDialog open={novelOpen} onClose={() => setNovelOpen(false)} />
    </div>
  );
}
