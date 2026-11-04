import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Project, Style } from "@/lib/types";
import { useConfig } from "@/lib/config";
import { enumOf, labelFor } from "@/lib/labels";
import { HAS_PREVIEWS, themeCard, type Look } from "@/lib/styles";
import { useToast } from "@/lib/toast";
import { Card, Field, Select, Input, SubHeading } from "@/components/ui/primitives";
import type { UseProjectState } from "./project-view";
import { StylePicker } from "./style-picker";

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
  // What the theme "auto" follows: a novel part's genre; any other reel has none.
  const genre = project.path === "novel" ? project.novel?.genre ?? "auto" : null;
  const autoTheme =
    genre === null
      ? "Auto (none: only a novel part has a genre)"
      : genre === "auto"
        ? "Auto (the novel's genre, not chosen yet)"
        : genre === "other"
          ? "Auto (the novel's genre: Other, no theme)"
          : `Auto (the novel's genre: ${labelFor("genre", genre)})`;
  const themes = enumOf(config.style, "theme");
  // On the picker, "auto" shows the theme it comes to: none for a reel that is not a novel part
  // or a novel of another genre, nothing yet while Muse Spark has not picked the genre.
  const autoPreview = genre === null || genre === "other" ? "none" : genre === "auto" ? null : genre;
  const autoShort =
    genre === null || genre === "other" ? "No theme" : genre === "auto" ? "Not picked yet" : themeCard(genre)?.name ?? genre;
  const backgroundHint =
    style.background === "dalang"
      ? `Your own video, the characters standing at the bottom and the pictures up top. SAM 3.1 cuts you out${cutoutCost} to step back under the pictures; Scene also puts the pictures behind you, Studio a backdrop.`
      : `SAM 3.1 cuts you out${cutoutCost}, when processing or rendering with your key. ${
          style.background === "scene"
            ? "Each photo fills the screen behind you."
            : "A dark backdrop glowing in your highlight colour."
        }`;

  return (
    <Card title="Style">
      <div className="flex flex-col gap-3">
        <SubHeading>Pictures</SubHeading>
        <SelectField name="visual_style" label="Look" hint={pictureHint} />
        <SelectField name="visuals" label="How many" />
        <SelectField name="picture_layout" label="Layout" hint="Each picture can also be changed in Review." />
        <SelectField
          name="speaker_room"
          label="When a picture is up top"
          hint={
            style.speaker_room === "auto"
              ? "You step back, smaller, so the picture never covers you, and come back when it goes. SAM 3.1 cuts you out for it: in your own video you stand in front of a blurred copy of your room; in Studio, in front of the backdrop."
              : undefined
          }
        />
        <SelectField name="speaker_behind" label="Speaker behind a card or cut-out" />
        <SelectField
          name="effects"
          label="Effects"
          hint={
            style.effects === "on"
              ? "Free, at render: the theme's particles, photo cards that slowly grow, characters that breathe and slide in, the character you voice moving with your voice, a punch-in on your face at the hook and the cliffhanger, the room going dark round you at the cliffhanger, a rim of light as you step back, and horror's echo on the stressed words."
              : undefined
          }
        />
        {style.effects === "on" ? (
          <div className="grid grid-cols-2 gap-3">
            <SelectField name="punch_in" label="Punch-in" />
            <SelectField name="particles" label="Particles" />
          </div>
        ) : null}
        <SelectField
          name="pauses"
          label="Pauses"
          hint={
            style.pauses === "trim"
              ? "Free, at render: every silence over 0.7 s is cut to about half a second. The timeline here stays on your recording."
              : undefined
          }
        />
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
        <SelectField
          name="caption_language"
          label="Language"
          hint={
            style.caption_language !== "spoken"
              ? "Muse Spark translates the captions sentence by sentence at your next render with your key (about a cent a minute of video), each sentence shown while you say it. Your spoken captions are kept: switching back is free."
              : undefined
          }
        />

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
        {HAS_PREVIEWS ? (
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-semibold text-muted-foreground">Behind you, and the theme</span>
            <StylePicker
              look={style.background as Look}
              theme={style.theme ?? "auto"}
              autoTheme={autoPreview}
              autoLabel={autoShort}
              onChange={(background, theme) => update({ background, theme })}
            />
            <span className="text-xs text-muted-foreground/80">
              {backgroundHint} Themes are free: the colour of your video, the cards, the title, a backdrop and an
              effect on the stressed words. A theme sets the caption style and highlight while those are Highlight
              pill and red.
            </span>
          </div>
        ) : (
          <>
            {themes.length ? (
              <Field
                label="Theme"
                hint="A genre look over any background, at no cost: the colour of your video, the cards, the title, a backdrop and an effect on the stressed words. It uses its own caption style and highlight while those are Highlight pill and red."
              >
                <Select value={style.theme ?? "auto"} onChange={(e) => update({ theme: e.target.value })}>
                  {themes.map((v) => (
                    <option key={v} value={v}>
                      {v === "auto" ? autoTheme : labelFor("theme", v)}
                    </option>
                  ))}
                </Select>
              </Field>
            ) : null}
            <SelectField name="background" label="Behind you" hint={backgroundHint} />
          </>
        )}
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
