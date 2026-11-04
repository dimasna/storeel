# Storeel Studio

Turn a talking-head video, or an idea you record, into a captioned vertical reel with
Meta's Model API. The studio transcribes the speech, plans and draws pictures for the
moments that need them, and compiles a 1080×1920 reel with captions, the pictures and a
watermark.

## Try it

The studio runs at https://blogdimas3399--storeel-studio-web.us-east.modal.run. Bring your
own Meta Model API key (**Add key**, top right): it stays in your browser and goes to the
server only with an action that uses it. There, each browser sees only its own reels and
novels, and whatever is left untouched for 24 hours is deleted, so download your reel.

1. On the home page, scroll to **Pick a style for your reel**: one example part, made by the
   studio from one video, in its three looks and six themes.
2. Paste a chapter of a story (200 characters or more), pick a style and press send. Muse
   Spark writes the part (a hook, the beats, a poll and a call to action) and checks it
   against the chapter, and Muse Image draws its characters and pictures. A 3,000-character
   chapter costs about $0.33, or $0.56 in a look that cuts you out.
3. Read the part from the teleprompter, take by take, or upload one video of the whole part.
   Process it, then render (rendering is free).
4. Ask the editor for changes in your own words: "make it feel scarier", "pakai tema
   romance", "make me small in the bottom left corner".

## How it works

```
            ┌─ I have a video ───────► upload clips ──────────────────────┐
Create reel ┤                                                             ├─► transcribe ─► analyze ─► generate ─► compile
            ├─ Not yet ─► idea ─► scene script ─► record scene by scene ──┤
            └─ A novel ─► chapter ─► part script ─► record take by take ──┘ (pictures from the script and the bible)
```

| Step | Model | What it does |
| --- | --- | --- |
| Scene script (idea path) | Muse Spark 1.3, max effort | Writes a scene-by-scene script for a teleprompter, with the picture planned per scene |
| Transcribe | Muse Voice Transcribe | Speech turns with timing; words are then timed from the audio (see below) |
| Analyze | Muse Wonder 1.0, max effort (video) | Lists the characters, objects and places, and picks the moments that get a picture |
| Analyze | SAM 3.1 | Cuts those seen in the video out as reference images; checks the face when needed |
| Generate assets | Muse Image (+ SAM 3.1 for cut-outs) | Reference pictures for recurring entities, then one picture per moment |
| Stress | Muse Spark 1.3, low effort | Picks the words the word-by-word captions stress (a name at a reveal, a number, the punch of a line) |
| Title | SAM 3.1 (video) | Tracks the speaker through the first seconds, so the reel's title can stand behind their head |
| Background (optional) | SAM 3.1 (video) | Cuts the speaker out of the whole video, so a scene or a studio backdrop can go behind them |
| Compile | ffmpeg + Pillow, HyperFrames | Your video with the pictures floating over it (cards, SAM cut-outs, or full screen), captions, the title, watermark, loudness-normalised audio; HyperFrames renders a few entrances (below) |

Each text step has its own model and effort (`STOREEL_SCRIPT_*`, `STOREEL_PLAN_*`; see
`.env.example`). The defaults come from a comparison on the real API (October 2026; 3
scripts and 1 picture plan per setup, on a synthetic clip, so a small sample):

- **Scripts**: Muse Spark returned clean scripts every time (8 of 8). Muse Wonder's writing
  was as good, but 7 of 8 scripts had structural mistakes: the cat filed as an object or
  named "silver laptop", delivery notes written as labels, scene purposes mixed up, ids
  padded with random characters. Spark at `max` added the most concrete detail.
- **Picture plans**: Muse Wonder recognised the speaker in the video (so SAM cut her out and
  she appears in her own pictures), chose full-screen cutaways where a selfie close-up
  leaves no room for a card, and wrote more specific prompts. Muse Image drew equally well
  from either plan.

Every text-model answer is capped at `STOREEL_MAX_OUTPUT_TOKENS` (32,000, reasoning
included). A script that hits the cap is asked for once more; a picture plan that hits it
stops the job with a message.

## Setup

Needs Python 3.12 with [uv](https://docs.astral.sh/uv/) and ffmpeg (`brew install ffmpeg`).

```bash
uv sync
uv run storeel serve        # http://127.0.0.1:8000, or the next free port if 8000 is taken
```

Optional, for the motion graphics (Node 22 or newer): `cd motion && npm ci`. This installs
[HyperFrames](https://github.com/heygen-com/hyperframes) (Apache-2.0), pinned, which downloads
its headless Chrome on first use. Without it, the same layers come in with plain fades.

Each user brings their own Meta Model API key (create one in the Model API dashboard at
https://dev.meta.ai). Add it with **Add API key** at the top right of the studio; **Check
and save** asks Meta which models it can use. Usage is billed to that key.

Quick end-to-end check without the UI (upload, process and render one clip, then print the
Model API usage), with your own key in the environment or in `.env`:

```bash
MODEL_API_KEY='LLM|...' uv run storeel make path/to/clip.mp4 --language id --watermark @yourname
```

Every option is documented in `.env.example`. Projects, uploads and renders are stored in
`./data` (git-ignored).

## Using the studio

- **I have a video**: drop one or more clips (MP4, MOV or WebM; up to 3 minutes in total).
  Portrait works best; other shapes are centre-cropped to 9:16.
- **Start from an idea**: describe the idea, pick format, tone, length and language, and
  edit the script the script model writes. Record each scene in the browser (camera with the
  lines as a teleprompter, countdown, review, retake) or upload a take per scene.
- **Style**: picture look, how many pictures, the layout (cards and cut-outs over the speaker,
  or full screen), what the speaker looks like behind a picture (blurred, sharp, or blurred
  only when the picture covers the face), caption style, colour, case and position, the title
  over the first seconds (behind you, in front, or none, and its words), the look (*dalang*:
  your own video; *scene* or *studio*: you cut out in front of the pictures or a backdrop),
  a genre theme over that look (see "Genre themes"), the motion of the entrances, watermark
  text and position.
- **Review**: fix misheard caption words, hide a picture, show it as a card, a cut-out or full
  screen, or edit its prompt and regenerate it. "Update pictures" applies style changes and
  redoes only what changed.
- **Render**: optionally keep the file under 25 MB (the Messenger and Instagram DM limit).

The browser only allows the camera on `localhost` or HTTPS. To record on a phone, put the
studio behind an HTTPS tunnel and add the tunnel's host name to `STOREEL_ALLOWED_HOSTS`.

## How it works

- **Clips** are normalised first (1080×1920, one frame rate for the reel, H.264 BT.709,
  AAC 48 kHz), so the transcript, SAM coordinates and compositor share one timeline.
  Rotation flags are honoured; HDR (HLG) phone footage is mapped to SDR approximately.
- **Word timing**: Muse Voice Transcribe returns turns, not word timestamps, and its turn
  edges trail the speech. A loudness envelope finds where speech actually runs and pauses;
  the pauses are matched to sentence and clause ends, and words share each stretch by
  syllables. Edited captions are re-timed over the same speech.
- **Pictures follow the words**: the plan model quotes the words each picture illustrates, and
  the quote is located in the timed transcript, so a picture starts on its word.
- **How pictures are shown**: your video always fills the
  frame and pictures float over it. A card is the whole picture (3:2) in a dark rounded frame
  in the upper part of the frame. A cut-out is the subject alone: Muse Image draws it on a
  plain background and SAM cuts it out (one more SAM call, $0.0025); a character stands at
  the bottom on the side away from the face, an object floats in the upper middle. If SAM
  cannot find the subject, the picture is shown as a card. Pictures pop in with a short fade
  and rise. Behind them, the speaker is blurred and dimmed by default (fading over half a
  second), kept sharp, or blurred only when the picture covers the face (SAM checks the face
  while each picture is up). Full screen, with a slow zoom, is a layout setting and a choice
  per picture. The planner suggests a card or a cut-out for each picture; switching the
  layout redraws the pictures without planning them again.
- **Consistency** comes from reference images: what the video shows is cut out by SAM;
  what recurs but is not in the video gets a generated reference first.
- **Captions**: a highlight pill, a coloured word or plain text, a few words a page; or
  word by word ("bold" and "serif"), where each word comes in as it is said and the words
  Muse Spark chose to stress are set in a larger italic serif in the highlight colour. That
  choice is one small call after the transcription (about half a cent), kept on the words, so
  switching styles later is free; without it a simple rule stresses the longest word of a
  page. Word-by-word pages break at commas, so they read a phrase at a time.
- **The title behind you**: the reel's title (a novel part's: the novel's) comes in over the
  first three seconds. SAM 3.1 tracks you through that stretch of the video in one request
  (video segmentation, about $0.015), and the masks are decoded once and kept, so renders stay
  free. The compositor tries the title on two lines and on one, at every height in the upper
  half, and puts it where your head and shoulders cover a little of it but at least 70% of
  its letters show; their pixels where you are are taken out frame by frame. When you fill
  the frame so that no place is readable, it goes in front of you, as high as it can.
- **A background behind you** (optional; the default *dalang* look keeps your own video):
  SAM 3.1 tracks you through the whole video at 12 frames a second, in 20-second stretches
  sent side by side (about $0.0024 a second: $0.24 for a 100-second reel). Meta's mask
  decoder is pure Python, about a second a mask, so on the server the masks are shared out
  over many small machines at once; on your own computer a few processes decode them. They
  are kept as packed bits at half size, with the holes SAM leaves (a clip-on microphone)
  filled, and the compositor eases from one mask to the next, so the cut-out moves at the
  reel's frame rate and renders stay free.
  *Scene* puts each photo card's picture full screen behind you, slowly zooming, or panning
  across a wide one. *Studio* puts you in front of a dark backdrop with two slow glows in the
  highlight colour and a light outline; a photo card that would cover little of you goes
  behind you, one over your face stays in front. You are blurred only while a picture is in
  front of you. The title behind you reuses these masks.
- **Room for the pictures**, in every look: while a picture, a note, chat bubbles or the
  poll is up top, you step back, smaller about the bottom middle of your video, until the
  top of your head is just under it, and come back when it goes (eased over half a second;
  pictures that follow closely keep you back in between, so you never bob). The head comes
  from your masks when you are cut out, and from the face found in each take in your own
  video, which then shrinks over a blurred, dimmed copy of itself. You get no smaller than
  60%, and a picture that only grazes your hair moves nothing. It is free: the encoder
  scales your video frame by frame on the same curve the cut-out follows. *When a picture
  is up top* turns it off.
- **Your size and place** in the cut-out looks: make yourself smaller or bigger and move
  anywhere on the frame, with three sliders or by asking the editor ("make me small in the
  bottom left corner", "a bit bigger", "move me up a little"). The encoder scales and moves
  your video, and the same placement moves your cut-out, so they always line up. Moved or
  resized, you always have a backdrop: the pictures, and the studio glow between them. Your
  face check moves with you, and a single character stands on the side you leave free. The
  editor sees where you are on screen after each change, and offers to move the captions
  when they would cross your face.
- **Genre themes** dress any look for the kind of story it tells, at no cost (no model call,
  no SAM): a colour grade on your video, the caption style and highlight, the photo cards'
  frame, the title's colour and typeface, the studio backdrop, an effect on the stressed
  words and one touch of its own.

  | Theme | Grade and cards | Captions and title | Backdrop | Stressed words | Its own touch |
  | --- | --- | --- | --- | --- | --- |
  | Romance (*senja*) | warm; cream cards, rose border | serif in rose; cream serif title | a dusk sky, soft lights drifting up | a heartbeat | |
  | Horror | cold, desaturated, vignette; black cards, red edge | bold in acid green; pale title glowing red | a flickering green dark | shaking | cards glitch in |
  | Mystery (*noir*) | high-contrast black and white; tilted paper prints | bold in red; white title | a spotlight on a grainy wall | stamped down | every picture in black and white |
  | Drama (*sinetron*) | punchy contrast; dark cards, gold border | bold in gold; gold title | red and gold glows on a curtain | a zoom and a flash | letterbox bars |
  | Legend (*wayang*) | warm amber; dark-wood cards, gold border | serif in amber; gold serif title | a lamp-lit shadow-puppet screen | a glow | characters come in as shadow puppets |

  A theme sets the caption style and highlight only while you keep the defaults (Highlight
  pill, red); any other choice wins. *Auto* (the default) follows a novel part's genre (see
  "Novels"); other reels have no theme on Auto. *None* is the plain look. The editor sets a
  theme for the mood you ask for ("make it scarier", "pakai tema romance").
- **Style examples**: the home page and the style pickers show every look with every theme
  on one example part, *Sealed Since 1986* (an original story), made by the studio from one
  video: processed once, then rendered 18 ways, which is free after the first.
  `scripts/make_style_previews.py` cuts each render into a few silent seconds, taken at the
  same moments in each, and a still (`web/src/assets/styles`, about 3 MB in all). The home
  gallery plays a tile while it is on screen, a picker only the chosen one; with reduced
  motion every tile is a still. Without the examples, the pickers are plain menus.
- **Motion graphics**: three entrances are rendered by HyperFrames, an open-source
  HTML-to-video renderer, run locally: the title's letters rising in one by one, photo cards
  swinging in through 3D with a light crossing them, and a novel part's end screen coming in
  piece by piece. Pillow still draws every layer; HyperFrames only moves them, from fixed
  templates in `pipeline/motion.py` (the words and pictures go in as data, never as code; the
  fonts are the studio's own, so nothing is fetched). Its transparent frames are cached per
  reel, so a second render of the same reel costs nothing; if HyperFrames is missing or
  fails, the layers come in the plain way. Its telemetry, update checks and skill installs
  are switched off.
- **Jobs** run on background threads, one at a time per project, with progress, a log and
  cancel. Each stage reuses its output when its inputs have not changed, so retries and
  edits only redo what is missing.

## Privacy and cost

- **API keys**: the key stays in the user's browser. It is sent to the studio's server only
  with actions that start a job (writing a script, processing, regenerating a picture,
  rendering), held in memory until that job ends, and never written to the database, disk or
  logs. A restart forgets every key; jobs that were waiting are marked failed and can be
  started again. Rendering needs no key; given one, a render uses it only for what was chosen
  after processing (tracking you for a title behind you or a background, or finding your face).
- Every Model API request is sent with `store: false`. The video sent to the plan model is a
  small silent copy, uploaded with a one-hour expiry and deleted right after the call.
- The default models run in Standard mode. The cheaper `-contributor` Muse Spark models let
  Meta train on what you send; don't use them for other people's videos.
- The server has no login. On your own machine it binds to 127.0.0.1, rejects unknown Host
  headers and cross-site requests, and should not be exposed on a network you don't trust.
  Hosted (`modal_app.py`, with `STOREEL_PRIVATE_PROJECTS`), each browser sees only its own
  reels and novels, and anything untouched for `STOREEL_TTL_HOURS` is deleted.
- List prices: $0.01 per picture, $0.0025 per SAM image, $0.20 per 1,000 SAM video frames
  (at least 50 a request), $0.18 per hour of transcription, plus text-model tokens. Muse
  Wonder costs $4 per 1M input and $20 per 1M output tokens (Muse Spark: $1.25 and $4.25),
  and reasoning tokens count as output. With the defaults, a 30-second reel costs about
  $0.19: around $0.03 for the script, $0.09 for the picture plan, $0.05 for five pictures and
  $0.02 for the stressed words and the title's tracking. The studio shows each reel's usage
  and an estimate priced by the model that was used.

## Not verified yet

Both flows have been run end to end against the real Model API with Muse Spark 1.3 at
`medium` effort, on a generated selfie with synthetic speech (October 2026): script,
transcription, video analysis, SAM, Muse Image and the render all worked. Muse Image accepts
only the sizes `1024x1024`, `1024x1536` and `1536x1024` on the Responses API. Still to
confirm with real footage: SAM on real faces and objects, and how well the estimated word
timing tracks real speech.

## Development

```bash
uv run ruff check        # lint
uv run ruff format       # format
uv run storeel serve --port 8001
```

```
src/storeel/
  meta/        Model API client (Responses, Files, Voice), strict JSON schemas, SAM parsing
  media/       ffmpeg/ffprobe helpers and speech detection
  pipeline/    ingest, script, transcribe, analyze, detect, assets, layout, captions, compose,
               emphasis (stressed words), title + depth (the title behind you), cutout (you cut
               out for a background), themes + genre (genre themes), motion (HyperFrames)
  prompts/     model instructions (Markdown)
  web/         FastAPI app and the static single-page UI
  db.py        SQLite: project documents and the job queue
  jobs.py      worker threads and the job context
motion/        the pinned HyperFrames install (npm), and the page the server image renders once
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat(scope): …`, `fix(scope): …`).

## Novels

A novel is told as a series: one reel per chapter, called a
"part", and you are the storyteller.

- **A novel** has a title, a synopsis, a language (Indonesian or English), a narration style
  (casual, warm, dramatic or funny: it sets the voice and how part one opens, e.g. "Gue baru
  baca part satu novel X..." or "Aku baru baca..."), a picture look, a watermark and a genre
  (romance, horror, mystery, drama, legend or other: its parts' theme, see "Genre themes").
  On *Auto*, Muse Spark picks the genre from the synopsis and the chapter when the first
  part is written (one small call at low effort, under half a cent, kept on the novel); a
  failed call leaves it on Auto, so the parts have no theme yet. Paste each chapter's text.
- **The part script** (Muse Spark): a hook on camera with a fixed opening, the story in beats
  (part one's setup or a bridge from the previous part, rises, the turn, a cliffhanger), a
  poll and a call to action ("... lengkapnya ada di link bio"). Each beat says what the screen
  shows. The script is checked against the format and sent back for up to two fixes. Then a
  storyboard review reads the chapter next to it (is the quoted person on screen? is anything
  shown before it is said? does each outfit fit?) and sends its notes back for one rewrite
  (`STOREEL_STORY_REVIEW_EFFORT`, "off" to skip; one real review cost $0.047). Anything left
  is shown. Edit the words freely: edits keep your takes.
- **Recording**: one take per line of the part (the hook, each beat, the poll, then the call
  to action) to record with the teleprompter, or upload one video of the whole part. After
  processing, a take whose lines can't be heard in it (read from another version of the
  script, say) is flagged before you render.
- **Your own video**: already recorded the part your way? Upload it instead of writing a
  script ("Make it from my video"). It is transcribed and Muse Spark splits what you said into
  the hook and the beats, keeping your words (a stretch it leaves out goes back for a fix),
  then plans the pictures as usual. The poll screen and the end card appear only if you said
  a poll or a call to action. A part written from the chapter can switch to your video, and
  back.
- **The character bible** grows chapter by chapter. A new character is drawn full body and
  cut out by SAM; in a later part they are redrawn from that portrait in the new outfit, so
  the face stays the same. Each new portrait is checked by Muse Spark (one figure, whole body,
  the right look and outfit, the same face as before) and drawn once more with the checker's
  fix if it is wrong (`STOREEL_PICTURE_CHECK_EFFORT`; about $0.0035 a check). Recurring
  objects are kept too, and notes (a death, a secret) carry into later scripts. Part N sees
  only what earlier parts added.
- **On screen**, in the *dalang* look (the default, named after the shadow-puppet
  storyteller): a "Part N" badge from the first frame, the hook on the sharp speaker, then
  each beat's red tag, its photo card, scene, cut-out object, note or chat bubbles up top,
  and up to two characters standing at the bottom (a character's name over their head the
  first time you voice them). While a picture, a note or chats are up top, the speaker steps
  back, smaller, under it (see "Room for the pictures"), so it never covers their face (SAM
  finds the face once in each take, about $0.0025 a take). Then the poll
  screen and the end card. The *scene* and *studio* looks cut you out instead (see "A
  background behind you"). Pictures follow your recording: with one video of the whole part,
  each line starts where its words are heard.
- **Captions** are what Muse Voice Transcribe heard. Review them before you render: where a
  line follows the script but a word differs (a misheard name, a word said twice), the page
  shows the script's wording and can use it.
- **Cost** (October 2026, list prices): a 110-second part cost about $0.25 on the real API:
  $0.13 for the script (Muse Spark at max effort), eight to nine pictures and five SAM
  cut-outs, and the transcription. Later parts reuse the bible's pictures.

## Later: Messenger and Instagram

The flow lives in the backend (each step is an API action and the stage is derived from the
project), renders can be fitted under 25 MB, and media is addressed by storage keys, so a
chatbot channel can drive the same steps with quick replies.
