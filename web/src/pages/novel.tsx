import { useCallback, useEffect, useState } from "react";
import { Sparkles, X } from "lucide-react";
import { api, novelMediaUrl } from "@/lib/api";
import type { Novel } from "@/lib/types";
import { useToast } from "@/lib/toast";
import { requestKey } from "@/App";
import { labelFor } from "@/lib/labels";
import { Link, navigate } from "@/lib/router";
import { Card, Field, Input, Textarea, Pill, Banner } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import { NovelForm } from "@/components/app/novel-form";

export function NovelPage({ id }: { id: string }) {
  const { toast } = useToast();
  const [novel, setNovel] = useState<Novel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .getNovel(id)
      .then(setNovel)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [id]);

  useEffect(load, [load]);

  const run = async (fn: () => Promise<unknown>, success?: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      if (success) toast(success, "ok");
    } catch (e) {
      const err = e as { code?: string; message?: string };
      if (err.code === "api_key_required") requestKey("Add your Muse / Model API key to continue.");
      else toast(err.message || String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  if (error)
    return (
      <div className="flex flex-col gap-4 py-10">
        <Banner tone="error">{error}</Banner>
        <Link to="/" className="text-sm text-accent hover:underline">
          ← Back
        </Link>
      </div>
    );
  if (!novel)
    return (
      <div className="flex justify-center py-20">
        <div className="size-6 animate-spin rounded-full border-2 border-border-strong border-t-accent" />
      </div>
    );

  const openPart = (number: number) =>
    run(async () => {
      const project = await api.openChapterReel(id, number);
      navigate(`/p/${project.id}`);
    });

  // A showcase novel can't be changed, and opening a part is a POST that may create its reel,
  // so its existing reels are opened directly.
  const readOnly = novel.read_only;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <Link to={novel.read_only ? "/" : "/reels"} className="w-fit text-sm text-muted-foreground hover:text-foreground">
          {novel.read_only ? "← Home" : "← My reels"}
        </Link>
        <h1 className="font-display text-[2.4rem] leading-none tracking-[-0.01em] sm:text-[2.8rem]">{novel.title}</h1>
      </div>

      {readOnly ? (
        <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-accent/40 bg-accent/5 px-4 py-3 text-sm">
          <Sparkles className="size-4 shrink-0 text-accent" />
          <span className="flex-1 text-foreground">
            A showcase novel: open its parts to watch the reels. Start your own from the home page.
          </span>
          <Link to="/" className="font-semibold text-accent hover:underline">
            Make your own
          </Link>
        </div>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
        <div className="flex flex-col gap-5">
          <Card title="Chapters">
            <p className="mb-3 text-sm text-muted-foreground">
              Each chapter is one part of the series: one reel with a hook, the story, a poll and a
              call to action.
            </p>
            {novel.chapters.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted-foreground">
                      <th className="pb-2 pr-3 font-medium">Part</th>
                      <th className="pb-2 pr-3 font-medium">Title</th>
                      <th className="pb-2 pr-3 font-medium">Text</th>
                      <th className="pb-2 pr-3 font-medium">Reel</th>
                      <th className="pb-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {novel.chapters.map((c) => (
                      <tr key={c.number} className="border-t border-border">
                        <td className="py-2 pr-3">{c.number}</td>
                        <td className="py-2 pr-3">
                          {c.title || <span className="text-muted-foreground">untitled</span>}
                        </td>
                        <td className="py-2 pr-3 text-xs text-muted-foreground">
                          {c.chars.toLocaleString()} chars
                        </td>
                        <td className="py-2 pr-3">
                          {c.stage ? (
                            <Pill tone={c.renders ? "ok" : "default"}>
                              {c.renders ? `${c.renders} render${c.renders > 1 ? "s" : ""}` : c.stage}
                            </Pill>
                          ) : (
                            <span className="text-xs text-muted-foreground">not started</span>
                          )}
                        </td>
                        <td className="py-2">
                          <div className="flex items-center gap-1">
                            {readOnly && !c.project_id ? null : (
                              <Button
                                size="sm"
                                variant="primary"
                                onClick={() =>
                                  readOnly ? navigate(`/p/${c.project_id}`) : openPart(c.number)
                                }
                              >
                                {c.project_id ? "Open" : "Make the part"}
                              </Button>
                            )}
                            {readOnly ? null : (
                              <button
                                title="Delete chapter"
                                onClick={() =>
                                  confirm(
                                    `Delete chapter ${c.number}${c.project_id ? " and its reel" : ""}? What it added to the bible goes too.`,
                                  ) && run(async () => { await api.deleteChapter(id, c.number); load(); }, "Chapter deleted")
                                }
                                className="grid size-8 place-items-center rounded-lg border border-border-strong text-muted-foreground hover:text-foreground"
                              >
                                <X className="size-4" />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No chapters yet. Add the first one below.</p>
            )}
          </Card>

          {readOnly ? null : <AddChapter novel={novel} onAdded={load} run={run} />}
          <BibleSection novel={novel} />
        </div>

        <div className="flex flex-col gap-5">
          {readOnly ? (
            <NovelDetails novel={novel} />
          ) : (
            <>
              <Card title="The novel">
                <NovelForm
                  novel={novel}
                  saveLabel="Save"
                  onSave={(fields) => run(async () => { await api.editNovel(id, fields); load(); }, "Saved")}
                />
              </Card>
              <Card>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() =>
                    confirm(`Delete “${novel.title}”, its character bible and every part's reel?`) &&
                    run(async () => {
                      await api.deleteNovel(id);
                      navigate("/");
                    }, "Novel deleted")
                  }
                >
                  Delete novel
                </Button>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** The novel's settings as text, for a showcase novel nobody may edit. */
function NovelDetails({ novel }: { novel: Novel }) {
  const rows: [string, string][] = [
    ["Language", labelFor("novel_language", novel.language)],
    ["Narration style", labelFor("narration", novel.narration)],
    ["Picture look", labelFor("visual_style", novel.visual_style)],
    ["Genre", labelFor("genre", novel.genre ?? "auto")],
    ["Watermark", novel.watermark || "none"],
  ];
  return (
    <Card title="The novel">
      {novel.synopsis ? <p className="mb-3 text-sm text-muted-foreground">{novel.synopsis}</p> : null}
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function AddChapter({
  novel,
  onAdded,
  run,
}: {
  novel: Novel;
  onAdded: () => void;
  run: (fn: () => Promise<unknown>, success?: string) => Promise<void>;
}) {
  const { toast } = useToast();
  const [number, setNumber] = useState(String(novel.next_chapter));
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");

  const add = () => {
    if (text.trim().length < 200)
      return toast("Paste the whole chapter text (at least a few paragraphs)", "error");
    run(async () => {
      await api.addChapter(novel.id, {
        number: Number(number) || null,
        title: title.trim(),
        text,
      });
      setTitle("");
      setText("");
      onAdded();
    }, "Chapter added");
  };

  return (
    <Card title="Add a chapter">
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Part number">
            <Input type="number" min={1} max={999} value={number} onChange={(e) => setNumber(e.target.value)} />
          </Field>
          <Field label="Chapter title">
            <Input maxLength={160} placeholder="optional" value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
        </div>
        <Field label="Chapter text">
          <Textarea
            rows={8}
            maxLength={200000}
            placeholder="Paste the whole chapter text here"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </Field>
        <div>
          <Button variant="primary" onClick={add}>
            Add chapter
          </Button>
        </div>
      </div>
    </Card>
  );
}

function BibleSection({ novel }: { novel: Novel }) {
  const characters = Object.values(novel.bible.characters || {});
  const props = Object.values(novel.bible.props || {});
  if (!characters.length && !props.length)
    return (
      <Card title="Character bible">
        <p className="text-sm text-muted-foreground">
          Empty. The first part you process designs its characters here; later parts reuse them.
        </p>
      </Card>
    );

  const picture = (key: string | null, alt: string) =>
    key ? (
      <img src={novelMediaUrl(novel.id, key)} alt={alt} loading="lazy" className="size-16 shrink-0 rounded-lg object-cover" />
    ) : (
      <div className="grid size-16 shrink-0 place-items-center rounded-lg bg-background text-muted-foreground">
        {alt.slice(0, 1).toUpperCase()}
      </div>
    );

  return (
    <Card title="Character bible">
      <div className="flex flex-col gap-3">
        {characters.map((c) => {
          const latest = [...c.looks].sort((a, b) => b.chapter - a.chapter)[0];
          return (
            <div key={c.id} className="flex gap-3 rounded-2xl border border-border bg-background p-3">
              {picture(latest?.image ?? null, c.name)}
              <div className="min-w-0">
                <strong>{c.name}</strong>
                <small className="text-muted-foreground">
                  {" "}
                  “{c.label}” · {c.role} · since part {c.created_in}
                </small>
                <p className="mt-1 text-sm text-muted-foreground">{c.description}</p>
                {c.notes.map((n, i) => (
                  <p key={i} className="mt-1 text-xs text-muted-foreground">
                    Part {n.chapter}: {n.note}
                  </p>
                ))}
              </div>
            </div>
          );
        })}
        {props.map((p) => (
          <div key={p.id} className="flex gap-3 rounded-2xl border border-border bg-background p-3">
            {picture(p.image, p.id)}
            <div className="min-w-0">
              <strong>{p.id}</strong>
              <small className="text-muted-foreground"> object · since part {p.created_in}</small>
              <p className="mt-1 text-sm text-muted-foreground">{p.description}</p>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
