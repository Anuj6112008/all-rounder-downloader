# IGDesk Downloader

**IGDesk Downloader** is a fast, mobile-first web platform for downloading
**public** media. Paste a public link and get:

- 🎬 **Video** in selectable quality (up to 1080p+, always with audio — merged
  automatically when the platform separates streams)
- 🎵 **Audio** — native M4A/WEBM **and** MP3 (128 / 192 / 320 kbps)
- 🖼️ **Thumbnail** — best resolution as JPG / PNG / WEBP
- ℹ️ **Metadata** — title, uploader, duration, platform

**Launch platforms:** Instagram (public Reels/posts) · YouTube (videos & Shorts).
Other yt-dlp platforms (Facebook, X, TikTok, Pinterest, Reddit, Vimeo,
SoundCloud, Dailymotion) are listed as *coming soon* until they pass live tests —
never shown as broken.

> **Public content only.** Only download what you own or have permission to
> download. This tool never uses cookies, logins, proxies, captcha-solving or
> DRM circumvention, and it refuses private / login-required / DRM content.

Built entirely on the open-source [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)
engine. **No paid APIs, no API keys.**

---

## Architecture

Single **Vercel (Hobby)** project:

```
public/       Static frontend (vanilla HTML/CSS/JS, PWA, SEO pages)
api/index.py  One Python function (FastAPI / ASGI) serving all /api/*
backend/      Core: validation+SSRF, extractor, media pipeline, ffmpeg, config
tests/        pytest (unit + integration) and Playwright (frontend e2e)
docs/         DECISIONS.md (research, alternatives, decisions, failure log)
```

The three-tier **media pipeline** (see [`docs/DECISIONS.md`](docs/DECISIONS.md)):

| Tier | When | How |
|---|---|---|
| **A — Direct** | upstream URL carries `Content-Disposition: attachment` | `302` redirect to the CDN — zero server bandwidth |
| **B — Streaming proxy** | otherwise | chunked stream, **Range** support, size cap, no disk writes |
| **C — Merge / convert** | 1080p+ (split streams), MP3 | `ffmpeg -c copy` merge → fragmented MP4, or `libmp3lame` → MP3, both streamed from a pipe |

`ffmpeg` is bundled inside the Python function via the `imageio-ffmpeg` static
build (resolved: `FFMPEG_PATH` env → bundled binary → `PATH`), which is how it
fits within Vercel's **500 MB Python bundle / 300 s / 2 GB** free-tier envelope.

---

## Setup

```bash
git clone https://github.com/Anuj6112008/all-rounder-downloader.git
cd all-rounder-downloader

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # adjust if needed
```

Requirements: Python 3.11+. `ffmpeg`/`ffprobe` on PATH are needed for the
*integration* tests (the runtime uses the bundled `imageio-ffmpeg`).

---

## Run (local)

```bash
python run.py
# → http://127.0.0.1:8000  (serves both the site and /api)
```

The FastAPI app mounts `public/` in local dev, so one process serves the whole
site. On Vercel, static files are served by the platform and `/api/*` routes to
the function (see `vercel.json`).

---

## Test

```bash
# Unit tests (offline: validation, SSRF, platform detection, error mapping,
# format selection, filename sanitisation, API contract)
pytest tests/ -m "not integration"

# Integration tests (real public links; needs network + ffprobe)
TEST_BASE_URL=http://127.0.0.1:8000 pytest -m integration

# Everything
pytest
```

Frontend e2e (Playwright, mobile 390×844 + desktop 1440×900):

```bash
npm install
npx playwright install
npm run test:e2e                 # local
BASE_URL=https://<prod-host> npm run test:e2e   # production
```

---

## Deploy

Frontend + backend both live on **Vercel** (Hobby, free):

```bash
npm i -g vercel
vercel login
vercel                          # preview deployment
vercel --prod                   # production
```

Git integration (auto-deploys on push) is configured by importing the repo at
<https://vercel.com/new>. CI runs the full test suite on every push
(`.github/workflows/ci.yml`).

> **Reminder:** Vercel Hobby is **non-commercial** — ads or payments require
> Pro/Enterprise. See [Fair use — Commercial usage](https://vercel.com/docs/limits/fair-use-guidelines#commercial-usage).

---

## Update yt-dlp

`yt-dlp` is **pinned** in `requirements.txt`. To bump it:

```bash
pip install -U yt-dlp
pip show yt-dlp                  # note the new version
# edit requirements.txt: yt-dlp==<new-version>
pytest -m integration            # must pass before merging
git commit -am "chore: bump yt-dlp to <new-version>"
```

A **weekly GitHub Action** (`.github/workflows/ytdlp-weekly.yml`) tests the
latest `yt-dlp` against the live integration suite and opens a PR to bump the
pin automatically **only if tests pass**.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `INVALID_URL` on a valid link | URL failed validation | check scheme (`http/https`) and length (≤500); bare domains are auto-prefixed with `https://` |
| `UNSUPPORTED_PLATFORM` | domain not in the registry / platform not yet enabled | see `/api/platforms`; enable + add a real-link test first |
| `LOGIN_REQUIRED` | media is private / age-restricted | expected — public content only; no cookies are used by design |
| `GEO_BLOCKED` | platform geo-restriction | expected in the source region |
| `UPSTREAM_BLOCKED` (502) | platform rate-limiting or a CDN miss | retry shortly; the thumbnail path already falls back across variants |
| `TOO_LARGE` | over `MAX_FILE_BYTES` / `MAX_DURATION_SECONDS` | raise the env limits (and be mindful of the 300 s function cap) |
| integration test: `ffprobe not found` | ffmpeg not on PATH | `winget install Gyan.FFmpeg` (Windows) / `apt install ffmpeg` (Linux) |
| `AssertionError` from yt-dlp on boot | invalid `YoutubeDL` option | options are validated in `backend/extractor.py::_ydl_opts` |
| stale responses after editing code | old process still on :8000 | kill the listener, restart `run.py` (see DECISIONS.md F3) |

---

## Legal

- [Terms](public/terms.html) · [Privacy](public/privacy.html) ·
  [DMCA / removal](public/dmca.html) · [FAQ](public/faq.html) ·
  [About](public/about.html)
- MIT licensed — see [LICENSE](LICENSE).
- Research, limits and policy notes: [`docs/DECISIONS.md`](docs/DECISIONS.md).
