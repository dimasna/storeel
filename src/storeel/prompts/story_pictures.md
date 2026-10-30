THE PICTURES (descriptions in English, for an image model; every picture is generated):
- Each beat shows up to two characters standing at the bottom of the frame (ids), and AT MOST ONE of: a prop, a photo, a chat, a note; plus optionally a tag.
  - prop: a scene, an object, a detail or an empty place.
    - A SCENE is the moment itself: its people doing what the words say, in its place ("Bu Tini hands Pak Darto an envelope at the end of the alley at night while Laras watches from her doorway, trembling"). Set "refs" to the characters in it (at most two; their portraits are used to draw them), "people" to the exact number of figures, and describe the place, the poses and the action fully. A scene is shown as a framed picture. When something happens between people somewhere, show it as a scene of them doing it, not as an empty place with the people standing in front of it.
    - An OBJECT ("two identical red denture cases") is shown cut out of its background over the video; set "subject" to a short English noun phrase naming it for a segmentation model ("red denture case").
    - A DETAIL shot (hands gripping, an object held) gets "framing": "close-up".
    - An EMPTY PLACE (nobody in it: a dark kitchen, a street at night) gets "backdrop": true and is shown as a framed picture. Use it for the first look at a new place, or a mood with nobody in it; never as the background of people talking or acting there (that is a scene).
    - Describe what is there concretely: materials, colours, light, and what must NOT appear when it matters. Never show a character standing at the bottom AND inside a scene prop of the same beat.
  - note: writing the viewer must read - a note on the fridge, a sign, a text on a screen: {"text": "the words, at most 120 characters", "style": "paper|sign|screen"}. The image model cannot write, so NEVER ask for readable words, letters or numbers in a prop or photo: draw the object without writing and put the words in a note.
  - photo: a real-looking place, shown as a photo card with a caption ("title").
  - chat: one or two phone messages shown as chat bubbles: {"sender": "Ucup", "text": "..."} (at most 90 characters each).
  - tag: a red banner of one or two words for a reveal ("PLOT TWIST", "<<PREVIOUSLY>>").
- THE PICTURE FOLLOWS THE WORDS. While a sentence is spoken, the viewer must see who or what that sentence is about at that moment. Before choosing "show", write "see": one English sentence naming exactly who and what the viewer should be looking at while hearing this beat. Then make "show" deliver exactly that.
  - The person who speaks, is quoted or acts in the sentence is on screen. Never fill a beat with the main character by default.
  - Every person who speaks or acts on screen is a character, however minor: give them a character entry so they are designed once and look the same everywhere.
  - A reveal inside a long beat (about 80 characters or more) may switch the picture with "then": {"at": "two to five consecutive words copied exactly from the middle of the beat's text, where the switch happens", "show": {...}}. Use it only for a reveal, never just because the next words are about someone else. Without a switch, "then.at" is "".
  - Show only what has already been said or is being said; never a picture that reveals the next beat.
- PACE. A picture needs time to be seen (at least three seconds), and a screen that changes every few seconds tires the viewer. Keep it calm:
  - One moment, one picture. The beats of one moment (one place, the same people, one exchange) keep the same picture: repeat its prop or photo id in each of those beats, with the same people. Change the picture when the story moves to another moment, place or person.
  - A conversation is one moment: show it as one scene of the people talking, or with both of them standing at the bottom, for all its beats. Never cut back and forth to whoever is speaking.
- Almost every beat should show something. Use props for the objects the plot turns on.
- Characters are drawn as full-body portraits. "description" is who they are, the same in every chapter: apparent age, ethnicity, build, skin, face, hair, distinguishing marks - nothing they wear or hold. "outfit" is what they wear in THIS chapter: clothes with colours, shoes, headwear, accessories, chosen for where, when and why the chapter happens. Hands are empty unless they carry the thing through the whole chapter. "subject" is a short English noun for a segmentation model ("woman", "old man", "girl", "cat"). Injuries are shown tastefully, never gore.
- Never depict real public figures; describe a generic person instead.

THE CHARACTER BIBLE. The user message lists the characters already designed in earlier chapters: who they are ("description") and what they wore when last seen ("last_outfit").
- Reuse their ids. Never describe a bible character again in "characters".
- Dress them for THIS chapter. For every bible character the chapter shows (standing in a beat, or drawn in a scene prop's refs), add a "looks" entry: {"id": "<bible id>", "outfit": "English: what they wear in this chapter"}. Repeat the last_outfit only when this chapter continues the same day and nothing suggests they changed.
- If a character looks different only in some moments (an injury, a disguise, a ghost, soaked by rain), add a "variants" entry: {"id": "<base>_<what>", "base": "<character id>", "change": "English: what is different", "persistent": true|false}. Show the variant id in the beats where it applies; the base id elsewhere.
- New characters (first seen in this chapter) go in "characters" with a new id (lowercase snake_case of their name), a short on-screen "label" (lowercase, as viewers would call them), "role", "description", "outfit", "subject" and "slot" ("left" or "right": where they usually stand).
- "bible_notes": short notes in <<LANGUAGE>> on lasting changes worth remembering for later chapters (a death, an injury, a secret revealed), one per character. Only facts the chapter states outright.
- A prop that will matter again later gets "recurring": true. A recurring prop is stored in the bible and reused as the same picture, so its description is the object ALONE: no place, table, hands or people.
- Bible props (listed in the user message) may be shown again by id only when the object itself, alone, is what the beat shows.

ANSWER with one JSON object with every field of the schema. Empty values: "" for a missing prop, photo, tag or then.at, [] for no chat, {"text": "", "style": "paper"} for no note.
