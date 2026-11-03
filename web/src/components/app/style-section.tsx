import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Project, Style } from "@/lib/types";
import { useConfig } from "@/lib/config";
import { enumOf, labelFor } from "@/lib/labels";
import { useToast } from "@/lib/toast";
import { Card, Field, Select, Input, SubHeading } from "@/components/ui/primitives";
import type { UseProjectState } from "./project-view";

function RangeField({
  label,
  value,
  min,
  max,
  shown,
  hint,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  shown: string;
  hint?: string;
  onChange: (value: number) => void;
}) {
  return (
    <Field label={`${label} · ${shown}`} hint={hint}>
      <input
        type="range"
        min={min}
        max={max}
        step={0.01}
        value={value}
        aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-10 w-full cursor-pointer accent-primary"
      />
    </Field>
  );
}

export function StyleSection({ project, state }: { project: Project; state: UseProjectState }) {
  const config = useConfig();
  const { toast } = useToast();
  const [style, setStyle] = useState<Style>(project.style);
  const timer = useRef<number | null>(null);

  useEffect(() => setStyle(project.style), [project.style]);

  const save = async (next: Style) => {
    try {
      const updated = await api.setStyle(project.id, next as unknown as Record<string, unknown>);
      state.set(updated);
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const update = (patch: Partial<Style>, debounce = false) => {
    const next = { ...style, ...patch };
    setStyle(next);
    if (debounce) {
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => save(next), 600);
    } else {
      save(next);
    }
  };

  const SelectField = ({
    name,
    label,
    hint,
  }: {
    name: keyof Style;
    label: string;
    hint?: string;
  }) => {
    const values = enumOf(config.style, name);
    if (!values.length) return null;
    return (
      <Field label={label} hint={hint}>
        <Select
          value={style[name] as string}
          onChange={(e) => update({ [name]: e.target.value } as Partial<Style>)}
        >
          {values.map((v) => (
            <option key={v} value={v}>
              {labelFor(name, v)}
            </option>
          ))}
        </Select>
      </Field>
    );
  };

  const pictureHint = project.analysis ? "Picture changes apply when you update the pictures." : undefined;
  // SAM 3.1 video: 12 frames a second at $0.20 per 1,000 frames (see storeel.pipeline.cutout).
  const seconds = project.transcript?.duration || project.input_seconds || project.novel?.estimate.seconds || 0;
  const cutoutCost = seconds > 0 ? ` (about $${(seconds * 0.0024).toFixed(2)})` : "";

  return (
    <Card title="Style">
      <div className="flex flex-col gap-3">
        <SubHeading>Pictures</SubHeading>
        <SelectField name="visual_style" label="Look" hint={pictureHint} />
        <SelectField name="visuals" label="How many" />
        <SelectField name="picture_layout" label="Layout" hint="Each picture can also be changed in Review." />
        <SelectField name="speaker_behind" label="Speaker behind a card or cut-out" />
        {project.path === "video" ? <SelectField name="language" label="Spoken language" /> : null}

        <SubHeading>Captions</SubHeading>
        <SelectField name="captions" label="Style" />
        <div className="grid grid-cols-2 gap-3">
          <Field label="Highlight">
            <input
              type="color"
              value={style.caption_color}
              onChange={(e) => update({ caption_color: e.target.value.toUpperCase() })}
              className="h-10 w-full cursor-pointer rounded-xl border border-input bg-background p-1"
            />
          </Field>
          <SelectField name="caption_case" label="Case" />
        </div>
        <SelectField name="caption_position" label="Position" />

        <SubHeading>Title</SubHeading>
        <SelectField
          name="title_style"
          label="Over the first seconds"
          hint={
            style.title_style === "behind"
              ? "SAM tracks you so your head covers part of it (about $0.015, when processing or rendering with your key)."
              : undefined
          }
        />
        {style.title_style !== "off" ? (
          <Field label="Words" hint="Leave empty to use the reel's title.">
            <Input
              value={style.title_text}
              maxLength={40}
              placeholder={project.title.split(" - Part")[0]}
              onChange={(e) => update({ title_text: e.target.value }, true)}
            />
          </Field>
        ) : null}

        <SubHeading>Motion</SubHeading>
        <SelectField
          name="motion"
          label="Entrances"
          hint="The title's letters, photo cards swinging in through 3D, and a part's end screen."
        />

        <SubHeading>Look</SubHeading>
        <SelectField
          name="background"
          label="Behind you"
          hint={
            style.background === "dalang"
              ? `Your own video, the characters standing at the bottom and the pictures up top. SAM 3.1 can also cut you out${cutoutCost}: Scene puts the pictures behind you, Studio a backdrop.`
              : `SAM 3.1 cuts you out${cutoutCost}, when processing or rendering with your key. ${
                  style.background === "scene"
                    ? "Each photo fills the screen behind you."
                    : "A dark backdrop glowing in your highlight colour."
                }`
          }
        />
        {style.background !== "dalang" ? (
          <>
            <RangeField
              label="Your size"
              value={style.speaker_scale}
              min={0.3}
              max={1.6}
              shown={`${Math.round(style.speaker_scale * 100)}%`}
              onChange={(v) => update({ speaker_scale: v }, true)}
            />
            <RangeField
              label="Left to right"
              value={style.speaker_x}
              min={0}
              max={1}
              shown={style.speaker_x < 0.4 ? "Left" : style.speaker_x > 0.6 ? "Right" : "Middle"}
              onChange={(v) => update({ speaker_x: v }, true)}
            />
            <RangeField
              label="Up and down"
              value={style.speaker_y}
              min={0.6}
              max={1.8}
              shown={style.speaker_y < 0.97 ? "Raised" : style.speaker_y > 1.03 ? "Lowered" : "On the bottom"}
              hint="Moved or resized, you always have a backdrop: the pictures, and a soft glow between them."
              onChange={(v) => update({ speaker_y: v }, true)}
            />
            {style.speaker_scale !== 1 || style.speaker_x !== 0.5 || style.speaker_y !== 1 ? (
              <button
                type="button"
                className="self-start text-sm font-medium text-primary underline-offset-4 hover:underline"
                onClick={() => update({ speaker_scale: 1, speaker_x: 0.5, speaker_y: 1 })}
              >
                Reset your size and place
              </button>
            ) : null}
          </>
        ) : null}

        <SubHeading>Watermark</SubHeading>
        <Field label="Text">
          <Input
            value={style.watermark}
            maxLength={60}
            placeholder="@yourname"
            onChange={(e) => update({ watermark: e.target.value }, true)}
          />
        </Field>
        <SelectField name="watermark_position" label="Position" />
      </div>
    </Card>
  );
}
