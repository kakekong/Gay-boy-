# =====================================================================
# Render — Transmisi Eng backend
#
# Unlike infra/hfspace/Dockerfile, this does NOT clone from GitHub at
# build time: Render checks the repo out itself and hands us the working
# tree, so we just COPY it. That removes the whole class of "pushed to
# the wrong branch, so the rebuild deployed nothing" problem — whatever
# branch the service is connected to is what ships.
#
# Build context is ./backend (set in render.yaml), so every path below is
# relative to the backend directory.
#
# Config lives in render.yaml + the Render dashboard, not here. See
# docs/DEPLOY_RENDER.md for the values to paste in.
# =====================================================================
FROM python:3.11-slim

# Unbuffered so Render's log tail shows the [boot] lines as they happen
# rather than in a lump after the buffer fills.
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# build-essential + libpq-dev cover the packages without prebuilt wheels;
# tesseract-ocr is the binary pytesseract shells out to for OCR on scanned
# documents (app/ai/doc_parser.py — it degrades to a warning without it,
# so the image works either way, the feature just goes quiet).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential libpq-dev tesseract-ocr curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements first so a code-only push reuses the cached install layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Only used if STORAGE_BACKEND is left as "local" — the blueprint sets it to
# "s3" so attachments go to R2 instead. Kept as a sane default so the image
# still works on a host that mounts a disk at /data.
ENV STORAGE_LOCAL_DIR=/data/storage

# Render injects PORT and routes external traffic to it.
ENV PORT=10000
EXPOSE 10000

# Seed is best-effort on purpose — note the ';' rather than '&&'. It
# creates the chart of accounts and runs the forward-only data repairs,
# but a transient database hiccup during it must not stop the API from
# booting into a restart loop: the app's own lifespan re-runs the schema
# check with retries and starts anyway if the DB is slow to wake.
CMD ["sh", "-c", "python -m app.scripts.seed ; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
