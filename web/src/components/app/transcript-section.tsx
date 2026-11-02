import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { seconds } from "@/lib/format";
import { Card, Textarea } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";
import type { UseProjectState } from "./project-view";

export function TranscriptSection({ project, state }: { project: Project; state: UseProjectState }) {
  const transcript = project.transcript;
  if (!transcript) return null;
  if (!transcript.turns.length)
    return (
      <Card title="Captions">
        <p className="text-sm text-muted-foreground">
          No speech was recognised, so the reel has no captions.
        </p>
      </Card>
    );

  const notes = project.caption_notes || {};
  const scripted = project.path !== "video";

  return (
    <Card title="Captions">
      <p className="mb-4 text-sm text-muted-foreground">
        {scripted
          ? "Check the captions before you render. They are what Muse Voice Transcribe heard; fix any word it misheard. Words are re-timed over the same speech."
          : "Fix any word Muse Voice Transcribe misheard. Words are re-timed over the same speech."}
      </p>
      <ol className="flex flex-col gap-3">
        {transcript.turns.map((turn) => {
          const note = notes[turn.id];
          return (
            <li key={turn.id} className="flex gap-3">
              <span className="w-12 shrink-0 pt-2 text-xs text-muted-foreground">
                {seconds(turn.start)}
              </span>
              <div className="flex-1">
                <Textarea
                  key={turn.text}
                  rows={Math.min(5, Math.ceil(turn.text.length / 60))}
                  maxLength={2000}
                  defaultValue={turn.text}
                  onBlur={(e) => {
                    const value = e.target.value.trim();
                    if (value && value !== turn.text)
                      state.act(() => api.editTurn(project.id, turn.id, value), "Caption updated");
                  }}
                />
                {turn.text !== turn.original ? (
                  <small className="mt-1 block text-xs text-muted-foreground">
                    heard: {turn.original}
                  </small>
                ) : null}
                {note && note.script ? (
                  <div className="mt-2 rounded-xl border border-border bg-background p-3 text-sm">
                    {note.differs.length ? (
                      <span className="text-xs text-warning">
                        Not in the script: {note.differs.join(", ")}
                      </span>
                    ) : null}
                    <p className="my-1 text-muted-foreground">{note.script}</p>
                    <Button
                      size="sm"
                      onClick={() =>
                        state.act(
                          () => api.editTurn(project.id, turn.id, note.script!),
                          "Caption updated",
                        )
                      }
                    >
                      Use the script's words
                    </Button>
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
