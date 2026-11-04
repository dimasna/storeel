// The reel styles, with real examples: one example part, "Sealed Since 1986", made by Storeel
// from one video and rendered in every look with every theme. Each render is cut into
// a short silent loop and a still (scripts/make_style_previews.py), named <look>-<theme>.

const videos = import.meta.glob<string>("../assets/styles/*.mp4", { eager: true, query: "?url", import: "default" });
const stills = import.meta.glob<string>("../assets/styles/*.webp", { eager: true, query: "?url", import: "default" });

export type Look = "dalang" | "scene" | "studio";

export const LOOKS: { look: Look; name: string; blurb: string; cutout: boolean }[] = [
  { look: "dalang", name: "Dalang", blurb: "Your own video, the characters below and the pictures up top", cutout: false },
  { look: "scene", name: "Scene", blurb: "You, cut out in front of each picture", cutout: true },
  { look: "studio", name: "Studio", blurb: "You, cut out in front of a glowing backdrop", cutout: true },
];

export interface ThemeCard {
  theme: string; // Style.theme
  name: string;
  genre: string; // the kind of story it is made for
  blurb: string;
}

export const THEME_CARDS: ThemeCard[] = [
  { theme: "none", name: "Plain", genre: "Any story", blurb: "Highlight pill captions, nothing added" },
  { theme: "romance", name: "Senja", genre: "Romance", blurb: "Warm light, rose serif words that beat like a heart" },
  { theme: "horror", name: "Horror", genre: "Ghost stories", blurb: "Cold colour, a flickering dark, words that shake" },
  { theme: "mystery", name: "Noir", genre: "Mystery", blurb: "Black and white, tilted prints, stamped words" },
  { theme: "drama", name: "Sinetron", genre: "Drama", blurb: "Punchy colour, gold frames, letterbox bars" },
  { theme: "legend", name: "Wayang", genre: "Legend", blurb: "Amber light, a shadow-puppet screen, glowing words" },
];

export interface Preview {
  video: string; // a few seconds, silent, looping
  still: string;
}

/** The example of a look with a theme ("none": the plain look), when it was made. */
export function preview(look: string, theme: string): Preview | null {
  const name = `../assets/styles/${look}-${theme}`;
  const video = videos[`${name}.mp4`];
  const still = stills[`${name}.webp`];
  return video && still ? { video, still } : null;
}

/** Whether the examples are there at all (a checkout without them shows the plain pickers). */
export const HAS_PREVIEWS = preview("dalang", "none") !== null;

export function themeCard(theme: string): ThemeCard | undefined {
  return THEME_CARDS.find((c) => c.theme === theme);
}

export function lookName(look: string): string {
  return LOOKS.find((l) => l.look === look)?.name ?? look;
}
