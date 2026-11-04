# Storeel Studio, ready to run:  docker compose up --build   then open http://localhost:8000
#
# One image holds everything the studio needs: the Python server, ffmpeg, the web app (built
# here, so the host needs no Node or npm) and the HyperFrames motion renderer with Chromium.
# It builds natively for Intel/AMD and for Apple Silicon. Chromium comes from Debian's package
# because Google publishes no Chrome download for Linux arm64, and HyperFrames uses a system
# Chromium there; the same browser is used on both so the two images behave alike.
#
# Nothing secret is built in. Each user adds their own Meta Model API key in the browser.

# ---- Node, pinned once (the release modal_app.py deploys) ---------------------------------------
FROM node:22.23.4-bookworm-slim AS node-base

# ---- The web app: /build/web/dist ---------------------------------------------------------------
FROM node-base AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# vite.config.ts looks for a running backend on ports 8000-8019 when it loads. A build has none,
# so name one and skip the search.
ENV STOREEL_API=http://127.0.0.1:8000
RUN npm run build

# ---- HyperFrames, installed from motion/package-lock.json ---------------------------------------
FROM node-base AS motion
WORKDIR /app/motion
COPY motion/package.json motion/package-lock.json ./
ENV HYPERFRAMES_NO_TELEMETRY=1 \
    DO_NOT_TRACK=1 \
    HYPERFRAMES_NO_UPDATE_CHECK=1 \
    HYPERFRAMES_SKIP_SKILLS=1 \
    HYPERFRAMES_AGENT=1
RUN npm ci --no-audit --no-fund

# ---- Python dependencies from uv.lock, and the app's source -------------------------------------
FROM python:3.12-slim-bookworm AS pydeps
RUN pip install --no-cache-dir --root-user-action=ignore uv==0.11.33
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md ./
COPY src/ ./src/
# The project is installed in place (editable), so the code stays at /app/src: the studio finds
# motion/ next to it. Its bytecode is compiled now because the app user cannot write there.
RUN uv sync --frozen --no-dev && python -m compileall -q src

# ---- The studio ---------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS studio

# ffmpeg and Chromium from Debian (tini reaps the processes they leave behind)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg chromium tini \
 && rm -rf /var/lib/apt/lists/*
COPY --from=node-base /usr/local/bin/node /usr/local/bin/node

# The studio runs as an ordinary user and keeps its projects, uploads and renders in /data
# (a volume in docker-compose.yml)
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin storeel \
 && mkdir /data \
 && chown storeel:storeel /data

ENV HYPERFRAMES_BROWSER_PATH=/usr/bin/chromium \
    HYPERFRAMES_NO_TELEMETRY=1 \
    DO_NOT_TRACK=1 \
    HYPERFRAMES_NO_UPDATE_CHECK=1 \
    HYPERFRAMES_SKIP_SKILLS=1 \
    HYPERFRAMES_AGENT=1

# Render one tiny page now, as the user who will run the studio. If that works, the motion
# graphics are on. If it does not (some emulated or locked-down setups cannot run Chromium),
# HyperFrames is taken out of the image, so the studio draws plain entrances at once instead of
# waiting for each render to time out. The build succeeds either way.
COPY --from=motion /app/motion /app/motion
COPY motion/warmup /app/motion/warmup
RUN if runuser -u storeel -- env HOME=/home/storeel sh -c 'cp -r /app/motion/warmup /tmp/warmup && timeout -k 5 180 /app/motion/node_modules/.bin/hyperframes render /tmp/warmup --format png-sequence --fps 24 --output /tmp/warm --quiet --workers 1 && test -f /tmp/warm/frame_000001.png'; then \
      echo "HyperFrames check passed: motion graphics are on"; \
    else \
      echo "WARNING: HyperFrames could not render in this build, so motion graphics are off (plain entrances)"; \
      rm -f /app/motion/node_modules/.bin/hyperframes; \
    fi; \
    rm -rf /tmp/warmup /tmp/warm
USER storeel

COPY --from=pydeps /opt/venv /opt/venv
COPY --from=pydeps /app/src /app/src
COPY --from=web /build/web/dist /app/web_dist

# 0.0.0.0 is the address the server prints, so a click on that link is let in
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    STOREEL_DATA_DIR=/data \
    STOREEL_FRONTEND_DIR=/app/web_dist \
    STOREEL_ALLOWED_HOSTS=0.0.0.0

WORKDIR /app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/config', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["tini", "--"]
CMD ["storeel", "serve", "--host", "0.0.0.0", "--port", "8000"]
