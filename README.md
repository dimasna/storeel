# Storeel Studio

Turn a talking-head video, or an idea you record, into a captioned vertical reel with
Meta's Model API. The studio transcribes the speech, plans and draws pictures for the
moments that need them, and compiles a 1080×1920 reel with captions, the pictures and a
watermark.

```
            ┌─ I have a video ───────► upload clips ──────────────────────┐
Create reel ┤                                                             ├─► transcribe ─► analyze ─► generate ─► compile
            └─ Not yet ─► idea ─► scene script ─► record scene by scene ──┘
```

| Step | Model | What it does |
| --- | --- | --- |
| Scene script (idea path) | Muse Spark 1.3 | Writes a scene-by-scene script for a teleprompter, with the picture planned per scene |
| Transcribe | Muse Voice Transcribe | Speech turns with timing; words are then timed from the audio (see below) |
| Analyze | Muse Spark 1.3 (video) | Lists the characters, objects and places, and picks the moments that get a picture |
| Analyze | SAM 3.1 | Cuts those seen in the video out as reference images; finds the face so cards go beside it |
| Generate assets | Muse Image | Reference pictures for recurring entities, then one picture per moment |
| Compile | ffmpeg + Pillow | Your video, full-screen cutaways or picture cards, word-highlighted captions, watermark, loudness-normalised audio |

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
  edit the script Muse Spark writes. Record each scene in the browser (camera with the
  lines as a teleprompter, countdown, review, retake) or upload a take per scene.
- **Style**: picture look and how many pictures, caption style, colour, case and position,
  watermark text and position.
- **Review**: fix misheard caption words, hide a picture, switch it between full screen and
  a card, or edit its prompt and regenerate it. "Update pictures" applies style changes and
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
- **Pictures follow the words**: Muse Spark quotes the words each picture illustrates, and
  the quote is located in the timed transcript, so a picture starts on its word.
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
- Every Model API request is sent with `store: false`. The video sent to Muse Spark is a
  small silent copy, uploaded with a one-hour expiry and deleted right after the call.
- The default models run in Standard mode. The cheaper `-contributor` Muse Spark models let
  Meta train on what you send; don't use them for other people's videos.
- The server has no login. It binds to 127.0.0.1, rejects unknown Host headers and
  cross-site requests, and should not be exposed on a network you don't trust.
- At list prices a 60-second reel costs roughly $0.20–0.75: about $0.01 per picture,
  $0.0025 per SAM image, $0.18 per hour of transcription, plus Muse Spark tokens. The
  studio shows each reel's usage and an estimate.

## Not verified yet

The pipeline has been run end to end against a simulated Model API (request shapes checked
against the docs), on synthetic clips. Against the real API, only the authentication path
is confirmed (an invalid key gets `401 invalid_api_key`). Still to confirm with a real key
and real footage: Muse Image's actual output resolution, Muse Spark's token use for video,
SAM on real faces and objects, and how well the estimated word timing tracks real speech.

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

## Later: Messenger and Instagram

The flow lives in the backend (each step is an API action and the stage is derived from the
project), renders can be fitted under 25 MB, and media is addressed by storage keys, so a
chatbot channel can drive the same steps with quick replies.
