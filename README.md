# Storeel Studio

Turn a talking-head video, or an idea you record, into a captioned vertical reel with
Meta's Model API. The studio transcribes the speech, plans and draws pictures for the
moments that need them, and compiles a 1080×1920 reel with captions, the pictures and a
watermark.

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
| Compile | ffmpeg + Pillow | Your video with the pictures floating over it (cards, SAM cut-outs, or full screen), word-highlighted captions, watermark, loudness-normalised audio |

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
  only when the picture covers the face), caption style, colour, case and position, watermark
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
- **Jobs** run on background threads, one at a time per project, with progress, a log and
  cancel. Each stage reuses its output when its inputs have not changed, so retries and
  edits only redo what is missing.

## Privacy and cost

- **API keys**: the key stays in the user's browser. It is sent to the studio's server only
  with actions that start a job (writing a script, processing, regenerating a picture),
  held in memory until that job ends, and never written to the database, disk or logs. A
  restart forgets every key; jobs that were waiting are marked failed and can be started
  again. Rendering needs no key.
- Every Model API request is sent with `store: false`. The video sent to the plan model is a
  small silent copy, uploaded with a one-hour expiry and deleted right after the call.
- The default models run in Standard mode. The cheaper `-contributor` Muse Spark models let
  Meta train on what you send; don't use them for other people's videos.
- The server has no login. It binds to 127.0.0.1, rejects unknown Host headers and
  cross-site requests, and should not be exposed on a network you don't trust.
- List prices: $0.01 per picture, $0.0025 per SAM image, $0.18 per hour of transcription,
  plus text-model tokens. Muse Wonder costs $4 per 1M input and $20 per 1M output tokens
  (Muse Spark: $1.25 and $4.25), and reasoning tokens count as output. With the defaults, a
  30-second reel costs about $0.17: around $0.03 for the script, $0.09 for the picture plan
  and $0.05 for five pictures. The studio shows each reel's usage and an estimate priced by
  the model that was used.

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
  pipeline/    ingest, script, transcribe, analyze, detect, assets, layout, captions, compose
  prompts/     model instructions (Markdown)
  web/         FastAPI app and the static single-page UI
  db.py        SQLite: project documents and the job queue
  jobs.py      worker threads and the job context
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat(scope): …`, `fix(scope): …`).

## Novels

A novel is told as a series: one reel per chapter, called a
"part", and you are the storyteller.

- **A novel** has a title, a synopsis, a language (Indonesian or English), a narration style
  (casual, warm, dramatic or funny: it sets the voice and how part one opens, e.g. "Gue baru
  baca part satu novel X..." or "Aku baru baca..."), a picture look and a watermark. Paste
  each chapter's text.
- **The part script** (Muse Spark): a hook on camera with a fixed opening, the story in beats
  (part one's setup or a bridge from the previous part, rises, the turn, a cliffhanger), a
  poll and a call to action ("... lengkapnya ada di link bio"). Each beat says what the screen
  shows. The script is checked against the format and sent back for up to two fixes; anything
  left is shown. Edit the words freely: edits keep your takes.
- **Recording**: one take per line of the part (the hook, each beat, the poll, then the call
  to action) to record with the teleprompter, or upload one video of the whole part.
- **The character bible** grows chapter by chapter. A new character is drawn full body and
  cut out by SAM; in a later part they are redrawn from that portrait in the new outfit, so
  the face stays the same. Recurring objects are kept too, and notes (a death, a secret)
  carry into later scripts. Part N sees only what earlier parts added.
- **On screen**: a "Part N" badge from the first frame, the hook on the sharp speaker, then
  the speaker blurred behind each beat's red tag, its photo card, scene, cut-out object, note
  or chat bubbles, and up to two characters standing at the bottom. Then the poll screen and
  the end card. Pictures follow your recording: each take's words are shared out among its
  beats.
- **Cost** (October 2026, list prices): a 110-second part cost about $0.25 on the real API:
  $0.13 for the script (Muse Spark at max effort), eight to nine pictures and five SAM
  cut-outs, and the transcription. Later parts reuse the bible's pictures.

## Later: Messenger and Instagram

The flow lives in the backend (each step is an API action and the stage is derived from the
project), renders can be fitted under 25 MB, and media is addressed by storage keys, so a
chatbot channel can drive the same steps with quick replies.
