// The effects, shown by example on the home page's showcase: each is a few seconds of the
// example part where it happens (scripts/make_effect_previews.py), in web/src/assets/effects.

const videos = import.meta.glob<string>("../assets/effects/*.mp4", { eager: true, query: "?url", import: "default" });
const stills = import.meta.glob<string>("../assets/effects/*.webp", { eager: true, query: "?url", import: "default" });

export interface EffectCard {
  id: string;
  name: string;
  blurb: string;
  /** How it is set: on by default, or what to ask the editor for it. */
  how: string;
}

export const EFFECT_CARDS: EffectCard[] = [
  { id: "title", name: "Title behind you", blurb: "The part's title over the first seconds, your head in front of it", how: "SAM 3.1 tracks you" },
  { id: "captions", name: "Word-by-word captions", blurb: "Each word comes in as you say it; Muse Spark stresses the punch words", how: "Bold or Serif captions" },
  { id: "punch", name: "Punch-in", blurb: "The shot cuts in on your face at the hook's end and the cliffhanger", how: "On by default · \"no zooms\"" },
  { id: "step-back", name: "Step back", blurb: "You step back under a picture, so it never covers you", how: "On by default · SAM 3.1 cut-out" },
  { id: "spotlight", name: "Spotlight", blurb: "The room goes dark round you at the cliffhanger", how: "On by default" },
  { id: "living", name: "Living pictures", blurb: "Photo cards slowly grow; the characters breathe and slide in", how: "On by default" },
  { id: "particles", name: "Theme particles", blurb: "Bokeh, mist, rain, sparkle or embers, by the theme", how: "On by default · \"no particles\"" },
  { id: "echo", name: "Horror echo", blurb: "A ghost of you trails each stressed word", how: "In the Horror theme" },
  { id: "translate", name: "Captions in 6 languages", blurb: "Muse Spark translates each sentence, shown as you say it", how: "Ask: \"English subtitles\"" },
];

export interface EffectPreview {
  video: string;
  still: string;
}

export function effectPreview(id: string): EffectPreview | null {
  const video = videos[`../assets/effects/${id}.mp4`];
  const still = stills[`../assets/effects/${id}.webp`];
  return video && still ? { video, still } : null;
}
