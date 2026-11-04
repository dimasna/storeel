import { useEffect, useState } from "react";
import { BookText, Plus, Sparkles } from "lucide-react";
import { api, mediaUrl } from "@/lib/api";
import type { NovelSummary, ProjectSummary } from "@/lib/types";
import { Link } from "@/lib/router";
import { useConfig } from "@/lib/config";
import { ago, expiresIn, seconds } from "@/lib/format";
import { Banner, Card } from "@/components/ui/primitives";
import { NewNovelDialog } from "@/components/app/new-novel-dialog";

const PATH_LABEL: Record<string, string> = {
  idea: "From an idea",
  novel: "Novel part",
  video: "From a video",
};

/** Everything this browser made: its reels and its novels, plus the showcase. */
export function ReelsPage() {
  const config = useConfig();
  const ttl = config.ttl_hours ?? 0;
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [novels, setNovels] = useState<NovelSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [novelOpen, setNovelOpen] = useState(false);

  useEffect(() => {
    api.listProjects().then(setProjects).catch((e) => setError(String(e.message || e)));
    api.listNovels().then(setNovels).catch(() => setNovels([]));
  }, []);

  const mine = (projects ?? []).filter((p) => !p.read_only);
  const showcase = (projects ?? []).filter((p) => p.read_only);
  const myNovels = (novels ?? []).filter((n) => !n.read_only);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">My reels</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The reels and novels made in this browser.
          {ttl ? ` Each is kept for ${ttl} hours after you last touch it: download your reels.` : ""}
        </p>
      </div>

      <Card title="Reels">
        {error ? (
          <Banner tone="error">{error}</Banner>
        ) : projects === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : mine.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No reels yet. <Link to="/" className="text-accent hover:underline">Paste a chapter</Link> to make your first.
          </p>
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
                  <span className="grid h-14 w-10 shrink-0 place-items-center rounded-md bg-panel-tile text-muted-foreground">
                    {p.path === "idea" ? "✎" : p.path === "novel" ? "❡" : "▶"}
                  </span>
                )}
                <span className="flex min-w-0 flex-1 flex-col">
                  <strong className="truncate text-sm">{p.title}</strong>
                  <small className="text-xs text-muted-foreground">
                    {PATH_LABEL[p.path]} · {p.stage}
                    {p.input_seconds ? ` · ${seconds(p.input_seconds)}` : ""} · {ago(p.updated_at)}
                    {ttl ? ` · ${expiresIn(p.updated_at, ttl)}` : ""}
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
        title="Novels"
        actions={
          <button onClick={() => setNovelOpen(true)} className="inline-flex min-h-9 items-center gap-1 text-sm text-accent hover:underline">
            <Plus className="size-4" /> New novel
          </button>
        }
      >
        {novels === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : myNovels.length === 0 ? (
          <p className="text-sm text-muted-foreground">None yet. A novel keeps its characters the same from part to part.</p>
        ) : (
          <div className="flex flex-col gap-1">
            {myNovels.map((n) => (
              <Link
                key={n.id}
                to={`/n/${n.id}`}
                className="flex items-center gap-3 rounded-xl border border-transparent p-2.5 transition-colors hover:border-border hover:bg-background"
              >
                <span className="grid size-10 place-items-center rounded-lg bg-panel-tile text-muted-foreground">
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

      {showcase.length ? (
        <Card title="Showcase">
          <div className="flex flex-col gap-1">
            {showcase.map((p) => (
              <Link
                key={p.id}
                to={`/p/${p.id}`}
                className="flex items-center gap-3 rounded-xl border border-transparent p-2.5 transition-colors hover:border-border hover:bg-background"
              >
                <span className="grid h-14 w-10 shrink-0 place-items-center rounded-md text-white" style={{ background: "var(--gradient-accent)" }}>
                  <Sparkles className="size-4" />
                </span>
                <span className="flex min-w-0 flex-col">
                  <strong className="truncate text-sm">{p.title}</strong>
                  <small className="text-xs text-muted-foreground">Watch and download · made with Storeel</small>
                </span>
              </Link>
            ))}
          </div>
        </Card>
      ) : null}

      <NewNovelDialog open={novelOpen} onClose={() => setNovelOpen(false)} />
    </div>
  );
}
