# DECISIONS.md — Architecture & Hosting Decisions

Project: **IGDesk Downloader**
This log records the real research, the alternatives considered, and the final
choice — including failures hit during the build and how each was resolved.

---

## 1. Requirement recap

Deliver, for **public content only**, driven entirely by the open-source
`yt-dlp` engine (no paid APIs, no API keys):

- Video in selectable quality **up to 1080p+ including audio**
- Audio: native M4A/WEBM **and** MP3 (128/192/320)
- Best-resolution thumbnail (JPG/PNG/WEBP)
- Metadata: title, uploader, duration, platform
- Platforms at launch: Instagram (public Reels/posts), YouTube (videos + Shorts)

Hard constraints: no cookies/logins/proxies/captcha/DRM, no permanent storage
of user files or links, secrets only via env vars, free hosting only.

---

## 2. Free-tier research (verified against OFFICIAL docs)

### Vercel (chosen primary host)

| Limit | Hobby plan value | Source |
|---|---|---|
| Function max duration | **300 s (5 min)** default and max | [Vercel — Configuring max duration](https://vercel.com/docs/functions/configuring-functions/duration) · [Function limitations](https://vercel.com/docs/functions/limitations) |
| Function memory / CPU | **2 GB / 1 vCPU** (default and max) | [Function limitations](https://vercel.com/docs/functions/limitations) |
| Function **bundle size** | **500 MB** for Python (250 MB other runtimes) | [Function limitations — Bundle size](https://vercel.com/docs/functions/limitations#bundle-size-limits) |
| Request/response payload | 4.5 MB (streamed responses are not payload-limited the same way) | [Function limitations — Request body](https://vercel.com/docs/functions/limitations) |
| Build time per deployment | 45 min | [Limits](https://vercel.com/docs/limits/overview) |
| CLI static file upload (Hobby) | 100 MB source files | [Limits — Static file uploads](https://vercel.com/docs/limits/overview) |
| Included Fast Data Transfer | **first 100 GB / month** | [Fair use guidelines](https://vercel.com/docs/limits/fair-use-guidelines) |
| Included invocations | first 1,000,000 / month | [Fair use guidelines](https://vercel.com/docs/limits/fair-use-guidelines) |
| Included Active CPU | **4 hours / month** | [Fair use guidelines](https://vercel.com/docs/limits/fair-use-guidelines) |
| Included Provisioned Memory | **360 GB-hrs / month** | [Fair use guidelines](https://vercel.com/docs/limits/fair-use-guidelines) |
| Proxied request timeout | 120 s | [Limits — Proxied request timeout](https://vercel.com/docs/limits/overview) |
| **Commercial use** | **Hobby = non-commercial personal use only.** Ads or payment require Pro/Enterprise. | [Fair use guidelines — Commercial usage](https://vercel.com/docs/limits/fair-use-guidelines#commercial-usage) |

**Key implication:** a Python function may run up to **300 s** with **2 GB RAM**
and may bundle up to **500 MB** — enough to include a static `ffmpeg` binary
(≈ 30 MB) + `yt-dlp`. That makes the *entire* media pipeline feasible on the
free Hobby plan **without** a second host.

### Fallback host evaluated (only if Vercel could not run ffmpeg)

| Host | Free-tier facts | Source |
|---|---|---|
| **Render** | Free web service: **0.1 CPU / 512 MB RAM**, **750 free instance-hours/month**, spins down after **15 min idle** (~1 min cold start), ephemeral FS, outbound bandwidth metered monthly. Free instances are explicitly *"not for production."* | [Render — Deploy for Free](https://render.com/docs/free) |
| **Hugging Face Spaces (Docker)** | Docker Spaces run a custom container (default port 7860); container user `uid 1000`; `/data` volume available at runtime only. Suitable if a container with `apt install ffmpeg` were needed. | [HF — Docker Spaces](https://huggingface.co/docs/hub/spaces-sdks-docker) |

**Decision:** Render/HF were kept as fallbacks but **not needed** — Vercel's
300 s / 2 GB / 500 MB envelope comfortably covers merge + MP3 for files under
the configured size/duration caps. Single-host architecture chosen (simplest
that passes all tests).

---

## 3. Architecture chosen

**Single Vercel project (Hobby):**

```
public/      → static frontend (HTML/CSS/JS, PWA, SEO pages) served by Vercel CDN
api/index.py → one Python function (FastAPI ASGI) handling all /api/*
backend/     → pure-Python core (validation, extractor, pipeline, ffmpeg, config)
```

Routing (`vercel.json`): `/api/(.*)` → the Python function, everything else →
`/public`. In local dev, the FastAPI app also mounts `public/` so
`python run.py` serves the whole site standalone.

### Media pipeline (3 tiers, as required)

- **A — Direct URL:** if the upstream URL already carries
  `Content-Disposition: attachment`, respond `302` to the CDN. Zero server
  bandwidth. (`ALLOW_DIRECT_REDIRECT=1`.)
- **B — Streaming proxy:** otherwise stream bytes in 64 KB chunks through the
  function, **forwarding `Range`** for seeking, with a hard size cap and time
  budget. Never writes the media to disk.
- **C — Merge/convert:** 1080p+ (separate video-only + audio-only streams) are
  merged with `ffmpeg -c copy` (no re-encode) into a **fragmented MP4**
  (`-movflags +frag_keyframe+empty_moov+default_base_moof`) streamed straight
  from `stdout` — required because a pipe is non-seekable. MP3 requests transcode
  via `libmp3lame` to the same pipe.

`ffmpeg` resolution order (never hardcoded):
`FFMPEG_PATH` env → bundled `imageio-ffmpeg` static build → `PATH`.
The `imageio-ffmpeg` wheel ships a pinned static binary **inside the Python
bundle**, which is how ffmpeg reaches Vercel's 500 MB function package.

### Why not the fallback host?

Merging/MP3 needs ffmpeg. Vercel bundles it (500 MB Python limit ≫ 30 MB) and
gives 300 s per request — enough for our size/duration caps. A container host
(Render/HF) adds a second deploy, CORS wiring, cold-start pings and its own
free-tier ceilings (Render: 0.1 CPU/512 MB, idle spin-down). Simpler architecture
wins; fallback stays documented in case Vercel constraints ever change.

---

## 4. Failures hit during the build (Failure Protocol log)

### F1 — `INVALID_URL` for every valid `https://` link

- **Symptom:** `POST /api/info` with a valid YouTube URL returned
  `{"error":{"code":"INVALID_URL"}}`.
- **Diagnosis (real evidence):** `normalize_url()` used
  `_SCHEME_RE.match(url.split("/", 1)[0])` → for `https://…` that token is
  `"https:"`, which failed the regex, forcing the schemeless path and then
  raising. Confirmed by calling `normalize_url()` in isolation.
- **Alternatives:**
  1. Repair the split-based scheme check (fragile — easy to reintroduce).
  2. Detect a scheme simply by the presence of `"://"`, and let `urlsplit()`
     validate the scheme afterward (robust, less code). ✅ **chosen**
- **Fix:** `if "://" not in url:` → only then consider the schemeless-bare-domain
  prepend; otherwise trust `urlsplit()`. Removed the now-unused `_SCHEME_RE`.
- **Re-test:** `normalize_url()` unit test + live `POST /api/info` → PASS.

### F2 — HTTP 500 `AssertionError` on extraction

- **Symptom:** `/api/info` returned 500; server log showed
  `unmapped extractor error: AssertionError`.
- **Diagnosis (real evidence):** ran extraction directly — traceback pointed at
  `yt_dlp/YoutubeDL.py … process_color_policy: assert policy in ('always',
  'never', 'no_color')`. My option `"color": "no"` was invalid.
- **Alternatives:**
  1. `"color": "no_color"` (valid literal). ✅
  2. Drop the `color` option entirely (quiet already disables progress). ✔ also valid
- **Fix:** `"color": "never"`. **Decision:** keep an explicit valid value so
  output colour can never leak into parsed logs.
- **Re-test:** live `POST /api/info` → real metadata returned. PASS.

### F3 — Stale process masking F1 during retest

- **Symptom:** after fixing F1, the endpoint still returned the old error.
- **Diagnosis:** `Get-NetTCPConnection` showed PID 7504 still listening on
  :8000 serving stale bytecode (uvicorn reloader had orphaned a child).
- **Fix:** killed every listener on :8000, restarted clean (no `--reload` for
  tests). **Lesson:** restart + confirm port owner before trusting a retest.

---

## 5. Security & compliance decisions

- **Input validation:** http/https only, ≤ 500 chars, no embedded credentials,
  URL normalisation (lowercase host, drop fragment) — `backend/validation.py`.
- **SSRF:** hostname and IP-literal checks block localhost, `.local/.internal`,
  loopback, private, link-local, reserved, multicast ranges **and** the cloud
  metadata address `169.254.169.254`. Media URLs are re-checked against a
  **separate CDN allowlist** (`validate_media_host`) immediately before any
  outbound fetch or ffmpeg input — defence in depth on the resolved URL, not
  just the user's URL.
- **Rate limiting:** per-IP sliding window (in-memory, best effort per warm
  serverless instance): info 30/min, download 10/min, thumb 20/min;
  `Retry-After` on 429.
- **Limits:** `MAX_FILE_BYTES` (300 MB), `MAX_DURATION_SECONDS` (1200 s),
  `JOB_BUDGET_SECONDS` (240 s) — all env-tunable.
- **CORS:** locked to `ALLOWED_ORIGINS` (env), local dev by default.
- **Security headers:** `X-Content-Type-Options`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`, `Permissions-Policy` — set on API responses in-app and
  on static pages via `vercel.json`.
- **yt-dlp options:** `noplaylist`, `quiet`, `socket_timeout`, cache confined to
  temp dir, `geo_bypass=False` (never spoof location), no post-processors that
  execute code. **Pinned** in `requirements.txt`.
- **No secrets:** everything via env (`.env.example`); the app uses no API keys.
- **No persistence:** media streamed, never stored; info cache is short-TTL
  in-memory only; history is opt-in `localStorage` and never sent to a server.
- **Logging:** hosts and error codes only — no full URLs, no file data.

---

## 6. Policy notes (must-read for going commercial)

- **Vercel Hobby is non-commercial.** Adding ads (e.g. AdSense), payments, or
  any monetisation requires Pro/Enterprise — or a different host. Source:
  [Fair use guidelines — Commercial usage](https://vercel.com/docs/limits/fair-use-guidelines#commercial-usage).
- **Platform Terms of Service:** this tool consumes public media via `yt-dlp`.
  Automating downloads may conflict with individual platforms' ToS. Users are
  responsible for downloading only content they own/are licensed to download.
- **DMCA:** we host no media. A removal contact form/endpoint is provided at
  `/dmca.html`; complete requests block the reported link from the allowlist.
