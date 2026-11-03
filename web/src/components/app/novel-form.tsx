import { useState } from "react";
import { useConfig } from "@/lib/config";
import { enumOf, labelFor } from "@/lib/labels";
import type { Novel } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea, Select } from "@/components/ui/primitives";

export interface NovelFields {
  title: string;
  synopsis: string;
  language: string;
  narration: string;
  visual_style: string;
  watermark: string;
  genre: string;
  [key: string]: unknown;
}

const EMPTY: NovelFields = {
  title: "",
  synopsis: "",
  language: "id",
  narration: "casual",
  visual_style: "realistic_3d",
  watermark: "",
  genre: "auto",
};

export function NovelForm({
  novel,
  saveLabel,
  onSave,
}: {
  novel?: Novel;
  saveLabel: string;
  onSave: (fields: NovelFields) => void;
}) {
  const config = useConfig();
  const [fields, setFields] = useState<NovelFields>({
    ...EMPTY,
    ...(novel
      ? {
          title: novel.title,
          synopsis: novel.synopsis,
          language: novel.language,
          narration: novel.narration,
          visual_style: novel.visual_style,
          watermark: novel.watermark,
          genre: novel.genre ?? "auto",
        }
      : {}),
  });

  const set = <K extends keyof NovelFields>(k: K, v: NovelFields[K]) =>
    setFields((f) => ({ ...f, [k]: v }));

  const sample = config.narration?.[fields.language]?.[fields.narration];

  return (
    <div className="flex flex-col gap-3">
      <Field label="Title">
        <Input
          value={fields.title}
          maxLength={120}
          placeholder="The novel's title"
          onChange={(e) => set("title", e.target.value)}
        />
      </Field>
      <Field label="Synopsis">
        <Textarea
          rows={3}
          maxLength={4000}
          value={fields.synopsis}
          placeholder="A few sentences about the story (optional, helps the script)"
          onChange={(e) => set("synopsis", e.target.value)}
        />
      </Field>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Language">
          <Select value={fields.language} onChange={(e) => set("language", e.target.value)}>
            {enumOf(config.novel, "language").map((v) => (
              <option key={v} value={v}>
                {labelFor("novel_language", v)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Narration style">
          <Select value={fields.narration} onChange={(e) => set("narration", e.target.value)}>
            {enumOf(config.novel, "narration").map((v) => (
              <option key={v} value={v}>
                {labelFor("narration", v)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Picture look">
          <Select value={fields.visual_style} onChange={(e) => set("visual_style", e.target.value)}>
            {enumOf(config.novel, "visual_style").map((v) => (
              <option key={v} value={v}>
                {labelFor("visual_style", v)}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {sample ? (
        <p className="text-xs text-muted-foreground">
          Part one opens: “{sample.opening}…” · {sample.voice}
        </p>
      ) : null}
      {enumOf(config.novel, "genre").length ? (
        <Field
          label="Genre"
          hint="Each part is dressed for it (unless the part picks its own theme): colours, cards, title and caption effects, at no cost. On Auto, Muse Spark picks it when the first part is written."
        >
          <Select value={fields.genre} onChange={(e) => set("genre", e.target.value)}>
            {enumOf(config.novel, "genre").map((v) => (
              <option key={v} value={v}>
                {labelFor("genre", v)}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}
      <Field label="Watermark" hint="Shown on every part, e.g. where to read the novel.">
        <Input
          value={fields.watermark}
          maxLength={60}
          placeholder="@yourname"
          onChange={(e) => set("watermark", e.target.value)}
        />
      </Field>
      <div>
        <Button variant="primary" onClick={() => onSave(fields)}>
          {saveLabel}
        </Button>
      </div>
    </div>
  );
}
