// The home page's gallery: mock frames of novel parts, one per picture look. The pictures were
// drawn by Muse Image (scripts/make_gallery.py); the badge, the title and the caption are laid
// over them here, the way a Storeel reel shows them.

import palacePromise from "@/assets/gallery/palace-promise.webp";
import gullPoint from "@/assets/gallery/gull-point.webp";
import animeLetter from "@/assets/gallery/anime-letter.webp";
import noirUmbrella from "@/assets/gallery/noir-umbrella.webp";
import comicHeist from "@/assets/gallery/comic-heist.webp";
import dragonQueen from "@/assets/gallery/dragon-queen.webp";
import chefCat from "@/assets/gallery/chef-cat.webp";
import musicBox from "@/assets/gallery/music-box.webp";
import villainIsekai from "@/assets/gallery/villain-isekai.webp";
import contractMarriage from "@/assets/gallery/contract-marriage.webp";

export interface GalleryTile {
  id: string;
  look: string; // the novel's visual_style
  genre: string;
  part: number;
  title: string;
  caption: string; // what the narrator says on this frame
  image: string;
  description: string; // what the picture shows, for screen readers
}

export const GALLERY: GalleryTile[] = [
  {
    id: "palace-promise",
    look: "illustration",
    genre: "Royal romance",
    part: 1,
    title: "Janji di Pendopo",
    caption: "besok dia menikahi orang lain",
    image: palacePromise,
    description: "A princess in a red kebaya holds back tears in a lantern-lit palace pavilion",
  },
  {
    id: "gull-point",
    look: "watercolor",
    genre: "Family mystery",
    part: 1,
    title: "The Bell That Rang Itself",
    caption: "nobody had rung that bell in years",
    image: gullPoint,
    description: "A girl with a lantern climbs a lighthouse's spiral stairs during a storm",
  },
  {
    id: "anime-letter",
    look: "anime",
    genre: "School romance",
    part: 4,
    title: "The Unsent Letter",
    caption: "she never sent the letter",
    image: animeLetter,
    description: "A schoolgirl holds a pink letter on a rooftop at sunset among cherry blossoms",
  },
  {
    id: "noir-umbrella",
    look: "cinematic",
    genre: "Crime thriller",
    part: 7,
    title: "The Red Umbrella",
    caption: "the witness was already gone",
    image: noirUmbrella,
    description: "A detective in the rain looks down at a red umbrella on a cobblestone street",
  },
  {
    id: "comic-heist",
    look: "comic",
    genre: "Action",
    part: 2,
    title: "The Midnight Heist",
    caption: "one jump, one chance",
    image: comicHeist,
    description: "A masked thief leaps between skyscrapers holding a glowing blue gem",
  },
  {
    id: "dragon-queen",
    look: "realistic_3d",
    genre: "Fantasy",
    part: 9,
    title: "The Dragon's Oath",
    caption: "the queen would not kneel",
    image: dragonQueen,
    description: "A young queen in a silver crown faces a black dragon in a throne hall",
  },
  {
    id: "chef-cat",
    look: "3d",
    genre: "Family comedy",
    part: 3,
    title: "Chef Mochi",
    caption: "the cat ate the wedding cake",
    image: chefCat,
    description: "An orange cat in a chef hat beside a half-eaten wedding cake, a shocked grandmother behind",
  },
  {
    id: "music-box",
    look: "illustration",
    genre: "Horror",
    part: 5,
    title: "The Music Box",
    caption: "it played by itself at midnight",
    image: musicBox,
    description: "A girl with a flashlight finds a glowing music box in a moonlit attic",
  },
  {
    id: "villain-isekai",
    look: "anime",
    genre: "Isekai fantasy",
    part: 1,
    title: "Reborn as the Villain",
    caption: "I woke up as the villain",
    image: villainIsekai,
    description: "A young man in a hoodie wakes in a glowing magic circle, surrounded by knights",
  },
  {
    id: "contract-marriage",
    look: "cinematic",
    genre: "CEO romance",
    part: 12,
    title: "The Contract Marriage",
    caption: "sign it, or lose everything",
    image: contractMarriage,
    description: "A woman signs a contract in a rainy penthouse office while a man waits by the window",
  },
];

/** A picture of each look, for the look picker (the first tile drawn in it). */
export function lookPicture(look: string): string | undefined {
  return GALLERY.find((t) => t.look === look)?.image;
}
