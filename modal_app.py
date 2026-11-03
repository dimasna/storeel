"""Deploy Storeel Studio on Modal.

The studio is a long-running, stateful FastAPI app: it shells out to ffmpeg, composes video
with Pillow, and runs multi-minute jobs on background worker threads whose progress the
browser polls. That does not fit a scale-to-zero, many-instance serverless model, so this
runs it as ONE always-warm CPU container (`min_containers=1`, `max_containers=1`) backed by a
persistent Modal Volume for its SQLite database and media files.

Nothing is kept for long: the web app's own cleanup thread deletes any project or novel left
untouched for 24 hours (see storeel.maintenance), so users download their reel within that
window. The cleanup runs in the web container, not a separate scheduled one: a second
container committing its copy of the SQLite file to the Volume would replace the web
container's copy (last write wins), losing whatever was saved in between. The showcase reels
are never deleted, and nobody can change them.

Each user still brings their own Muse / Model API key from the browser; the server holds it
in memory only for the job it starts (see storeel.services.KeyVault). There is no login: each
browser sees only its own reels and novels, plus the showcase (see storeel.web.owners).

Deploy:   modal deploy modal_app.py
Dev/test: modal serve modal_app.py      (hot-reloads; gives a temporary URL)

The frontend (web/dist) is built by `npm run build` before deploying; this image copies it in
and the FastAPI app serves it. Build it first:  cd web && npm install && npm run build
"""

from __future__ import annotations

from pathlib import Path

import modal

APP_NAME = "storeel-studio"
DATA_DIR = "/data"            # the Modal Volume mount: SQLite + all media live here
TTL_HOURS = 24               # projects/novels untouched this long are deleted
# Reels and novels everyone can watch and nobody can change, never deleted: a demo novel (its
# chapter reels come with it) and its Part 1 reel. Empty until the new demo reel is made.
SHOWCASE: tuple[str, ...] = ()
HERE = Path(__file__).parent

# The web app's image. It carries ffmpeg (required at startup), the Python dependencies, the
# storeel source, and the built frontend.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg")
    .pip_install(
        "fastapi>=0.162",
        "uvicorn>=0.35",
        "httpx>=0.28",
        "numpy>=2.3",
        "pillow>=12.0",
        "python-dotenv>=1.2",
        "python-multipart>=0.0.20",
        "meta-sam-parser>=0.1.0",
    )
    .env(
        {
            "STOREEL_DATA_DIR": DATA_DIR,
            # Serve the built React app baked in at /app/web_dist (see add_local_dir below).
            "STOREEL_FRONTEND_DIR": "/app/web_dist",
            # Modal serves the app at https://<workspace>--...modal.run; allow that host (and the
            # same-site SPA served from it) past the TrustedHost / CSRF guards.
            "STOREEL_ALLOWED_HOSTS": "*.modal.run,*.modal.host",
            # Hosted for other people: each browser gets only its own reels, plus the showcase,
            # and everything else is deleted after TTL_HOURS untouched.
            "STOREEL_PRIVATE_PROJECTS": "1",
            "STOREEL_SHOWCASE": ",".join(SHOWCASE),
            "STOREEL_TTL_HOURS": str(TTL_HOURS),
            "PYTHONPATH": "/app",
        }
    )
    # Local files must be added LAST (Modal mounts them at container start, not image build).
    .add_local_dir(HERE / "src" / "storeel", remote_path="/app/storeel", ignore=["__pycache__"])
)

# Bake the built single-page app into the image when it is present, so the FastAPI app can serve
# it from /static. `web/dist` is produced by `npm run build`; keep the build out of the repo but
# run it before `modal deploy`.
_dist = HERE / "web" / "dist"
if _dist.is_dir():
    image = image.add_local_dir(_dist, remote_path="/app/web_dist")

app = modal.App(APP_NAME)
volume = modal.Volume.from_name(f"{APP_NAME}-data", create_if_missing=True)


@app.function(
    image=image,
    volumes={DATA_DIR: volume},
    cpu=4.0,
    memory=8192,
    min_containers=1,          # always warm: jobs run on in-process threads
    max_containers=1,          # single instance: one SQLite writer, one in-memory key vault
    timeout=60 * 60,           # a long render must not be cut off mid-flight
    scaledown_window=60 * 20,
)
@modal.concurrent(max_inputs=100)  # one ASGI app serving many concurrent HTTP requests
@modal.asgi_app()
def web():
    from storeel.web.app import create_app

    return create_app()
