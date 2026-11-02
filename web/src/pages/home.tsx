import { useEffect, useState } from "react";
import { Film, Lightbulb, BookText, Plus } from "lucide-react";
import { motion } from "motion/react";
import { api, mediaUrl } from "@/lib/api";
import type { NovelSummary, ProjectSummary } from "@/lib/types";
import { useConfig } from "@/lib/config";
import { useToast } from "@/lib/toast";
import { navigate, Link } from "@/lib/router";
import { ago, seconds } from "@/lib/format";
import { Card, Banner } from "@/components/ui/primitives";
import { NewNovelDialog } from "@/components/app/new-novel-dialog";
import { EASE_OUT } from "@/lib/ease";

const PATH_LABEL: Record<string, string> = {
  idea: "From an idea",
  novel: "Novel part",
  video: "From a video",
};

export function HomePage() {
  const config = useConfig();
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

  const choices = [
    {
      icon: Film,
      title: "I have a video",
      desc: "Upload one or more clips. They are transcribed, pictures are planned and drawn, and the reel is compiled.",
      onClick: () => create("video"),
    },
    {
      icon: Lightbulb,
      title: "Start from an idea",
      desc: `Describe the idea. ${config.models.script_name} writes a scene script; you record it scene by scene with a teleprompter.`,
      onClick: () => create("idea"),
    },
    {
      icon: BookText,
      title: "From a novel",
      desc: "Paste a novel chapter by chapter. Each chapter becomes one part of a series, with the same characters in every part.",
      onClick: () => setNovelOpen(true),
    },
  ];

  return (
    <div className="flex flex-col gap-8">
      <section className="pt-4">
        <motion.h1
          initial={{ opacity: 0, y: 12, filter: "blur(6px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          transition={{ duration: 0.5, ease: EASE_OUT }}
          className="text-3xl font-bold tracking-tight sm:text-4xl"
        >
          Create a <span className="gradient-text">reel</span>
        </motion.h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">
          Captions, pictures and a watermark on your talking-head video, made with Meta's Muse
          models. Reels are kept for 24 hours — download yours before it expires.
        </p>
      </section>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {choices.map((c, i) => (
          <motion.button
            key={c.title}
            onClick={c.onClick}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: i * 0.06, ease: EASE_OUT }}
            whileHover={{ y: -3 }}
            className="gradient-ring group flex flex-col items-start gap-3 rounded-3xl border border-border bg-card/60 p-6 text-left backdrop-blur-sm transition-colors hover:border-accent/50"
          >
            <span className="grid size-11 place-items-center rounded-2xl border border-border-strong bg-background text-accent transition-colors group-hover:border-accent/50">
              <c.icon className="size-5" />
            </span>
            <strong className="text-lg">{c.title}</strong>
            <span className="text-sm leading-relaxed text-muted-foreground">{c.desc}</span>
          </motion.button>
        ))}
      </div>

      <Card
        title="Novels"
        actions={
          <button
            onClick={() => setNovelOpen(true)}
            className="inline-flex items-center gap-1 text-sm text-accent hover:underline"
          >
            <Plus className="size-4" /> New novel
          </button>
        }
      >
        {novels === null ? (
          <p className="text-sm text-muted-foreground">Loading novels…</p>
        ) : novels.length === 0 ? (
          <p className="text-sm text-muted-foreground">No novels yet.</p>
        ) : (
          <div className="flex flex-col gap-1">
            {novels.map((n) => (
              <Link
                key={n.id}
                to={`/n/${n.id}`}
                className="flex items-center gap-3 rounded-xl border border-transparent p-2.5 transition-colors hover:border-border hover:bg-background"
              >
                <span className="grid size-10 place-items-center rounded-lg bg-background text-muted-foreground">
                  ❡
                </span>
                <span className="flex min-w-0 flex-col">
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

      <Card title="Recent reels">
        {error ? (
          <Banner tone="error">{error}</Banner>
        ) : projects === null ? (
          <p className="text-sm text-muted-foreground">Loading projects…</p>
        ) : projects.length === 0 ? (
          <p className="text-sm text-muted-foreground">No reels yet.</p>
        ) : (
          <div className="flex flex-col gap-1">
            {projects.map((p) => (
              <Link
                key={p.id}
                to={`/p/${p.id}`}
                className="flex items-center gap-3 rounded-xl border border-transparent p-2.5 transition-colors hover:border-border hover:bg-background"
              >
                {p.cover ? (
                  <img
                    src={mediaUrl(p.id, p.cover)}
                    alt=""
                    className="h-14 w-10 shrink-0 rounded-md object-cover"
                  />
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

      <NewNovelDialog open={novelOpen} onClose={() => setNovelOpen(false)} />
    </div>
  );
}
