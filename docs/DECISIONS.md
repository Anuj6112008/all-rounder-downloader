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
- Platform at launch: **Instagram (public Reels/posts)** — the app is
  Instagram-dedicated (see decision 12 for why YouTube was removed).

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

### F4 — Deployed YouTube returned 401 `LOGIN_REQUIRED` for public videos

- **Symptom:** production `/api/info` for public YouTube links returned
  `401 LOGIN_REQUIRED`, while the same links passed locally. Instagram was
  unaffected on production.
- **Diagnosis (real evidence):** captured the deployed response body —
  `{"error":{"code":"LOGIN_REQUIRED",...}}` was *our own* mapping. The regex
  `_PRIVATE_RE` matched `confirm you're not a bot`, i.e. YouTube's
  automated-traffic check against the serverless datacenter IP — an
  IP-reputation signal, not a content-privacy setting.
- **Alternatives:**
  1. Re-map bot-checks to `UPSTREAM_BLOCKED` with an honest message
     ("automated-traffic check — try again shortly") + log a URL-redacted
     signature for diagnosis. ✅ **chosen (correctness, mandatory)**
  2. yt-dlp official `player_client` selection (`android,web` via
     `extractor_args`) — first-class extractor config, no cookies/keys.
     ✅ **chosen (mitigation attempt)**
  3. Retry-with-backoff — cheap but unlikely to defeat a persistent
     IP-based check. ✔ kept as a future option, not implemented.
  Forbidden alternatives explicitly avoided: cookies, proxy rotation,
  captcha solving, fingerprint spoofing.
- **Fix:** `_BOT_RE` checked before `_PRIVATE_RE`; bot-check →
  `UPSTREAM_BLOCKED`; `YOUTUBE_PLAYER_CLIENTS` env (default `android,web`)
  wired into `_ydl_opts` for YouTube only. Unit tests lock the mapping.
- **Re-test:** deployed + retested; Instagram full pipeline passes in
  production; YouTube behaviour documented honestly (see final report).

### F5 — Merged videos showed 00:00 duration in phone galleries

- **Symptom:** user-reported: Instagram Reel 720p+ downloads played but
  gallery showed **00:00 duration**.
- **Diagnosis (real evidence):** the merge path piped ffmpeg output to a
  non-seekable stdout, which forces a *fragmented* MP4
  (`+frag_keyframe+empty_moov`). Fragmented MP4 omits the standard `moov`
  atom layout that gallery apps read for duration.
- **Alternatives:**
  1. Merge to a seekable temp file in `/tmp` with `-movflags +faststart`
     (moov relocated to the front), stream the file, always delete in a
     `finally`. ✅ **chosen** — spec explicitly allows `/tmp` "if
     unavoidable"; a seekable output is impossible on a pipe, so it *is*
     the unavoidable case.
  2. Keep fragmented MP4 and post-process duration metadata — fragile,
     essentially hand-patching atoms. ✗ rejected.
  3. Re-encode to a container with inline duration — wastes CPU and
     quality for no reason. ✗ rejected.
- **Fix:** `merge_to_tempfile()` + `stream_file()` (delete-even-on-
  disconnect) in `backend/ffmpeg.py`; download route now serves the
  temp file with a real `Content-Length`.
- **Sub-failure during verification (F5a):** first retest returned 502;
  server log showed `File '...mp4' already exists` — `tempfile.mkstemp`
  pre-creates the file and ffmpeg refuses to overwrite without `-y`.
  **Fix:** added `-y`. **Re-test:** ffprobe on the merged download
  reports real duration > 0 and `moov` within the first 200 KB
  (faststart confirmed) — see final report for the live retest.

### F6 — E2E suite failed 7/28 right after pytest (rate-limit contention)

- **Symptom:** every Playwright test that made a **real Instagram fetch**
  timed out (44–45 s, `#result` never became visible); all 21 non-fetch
  tests passed. Backend suite (81 tests) had just passed against the
  same server.
- **Diagnosis (real evidence):** the in-memory limiter keys buckets by
  `X-Forwarded-For` else client host (`app.py::_client_ip`). pytest +
  e2e both hit `127.0.0.1`, so the integration suite spent the shared
  `127.0.0.1:info` (30/min) and `:download` (10/min) buckets before e2e
  started → 429 → frontend shows an error, card stays hidden → Playwright
  assertion times out. **Confirmed:** restarting the server (clears
  `_buckets`) made the previously-failing download test pass in
  isolation (2/2).
- **Alternatives:**
  1. Give every e2e test a unique `X-Forwarded-For` via
     `context.setExtraHTTPHeaders()` so each test owns its bucket.
     ✅ **chosen** — deterministic, mirrors the isolation pattern
     `test_negative.py`'s rate-limit test already uses; zero production
     code changed.
  2. Raise limits via env for test runs — ✗ rejected: weakens the real
     limiter and hides genuine contention instead of removing it.
  3. Sleep/pace the suite — ✗ rejected: slow and still flaky.
- **Fix:** `tests/e2e/ui.spec.js::beforeEach` sets a random
  `10.98.x.x` per test. **Retest:** failures dropped 7 → 2.

### F7 — History opt-in test failed on both viewports (invisible checkbox)

- **Symptom:** `history opt-in` test failed mobile **and** desktop even
  after F6; `--reporter=list` showed `waiting for element to be visible…
  element is not visible` on `#historyToggle.check()` (218 retries).
- **Diagnosis (real evidence):** the claymorphism switch re-styled the
  native checkbox to `position:absolute; opacity:0; width:0; height:0` —
  a 0×0 box is invisible to pointer input and to Playwright's actionability
  check. Regression introduced by the redesign (old UI had a visible
  20 px native checkbox).
- **Alternatives:**
  1. Keep the input real-sized (50×28, `opacity:0`) overlaying the clay
     track, `z-index:2` — ✅ **chosen**: restores clickability *and*
     keyboard/SR access (it was an a11y regression too, not just tests).
  2. `check({ force: true })` in the test — ✗ rejected: masks a real
     a11y bug for everyone.
  3. Drop the custom switch, restore the native checkbox — ✗ rejected:
     loses the clay design for no reason once the overlay works.
- **Fix:** `public/styles.css::switch input` overlay rule.
  **Retest:** history test 2/2 pass (9.3 s / 9.6 s).

### F8 — CI red: ffmpeg SIGSEGV (`rc=-11`) on GitHub runners

- **Symptom:** after the Instagram pivot commit, unit + non-fetch e2e passed
  but every ffmpeg-backed assertion failed in CI: merge → `502`, MP3 →
  0-byte body, e2e downloads → 90 s timeout; server log showed
  `backend.ffmpeg: merge failed (rc=-11)` (four times). `ffprobe`-based
  assertions (thumbnails, native-audio probe) **passed**.
- **Diagnosis (real evidence):** `rc=-11` = SIGSEGV. `find_ffmpeg()`
  resolves `FFMPEG_PATH` → `imageio-ffmpeg` wheel → PATH, so CI was using
  the imageio static Linux build (0.6.0 = johnvansickle ffmpeg 7.0.2
  static) while `ffprobe` came from apt — hence probe OK / ffmpeg crash.
  The new `scripts/ci_ffmpeg_diag.py` showed the nuance: on the runner the
  imageio build passes a **network-free synthetic encode** (`rc=0 OK`) but
  SIGSEGVs on **real Instagram HTTPS inputs** (4× `rc=-11` in the failing
  run); apt ffmpeg 6.1.1 handles both. The same imageio build works on
  Windows locally and on Vercel (AL2023, live 19/19 including merge+MP3) —
  so the crash is specific to that static build's real-input path on
  GitHub's runners.
- **Alternatives:**
  1. CI-only `FFMPEG_PATH=/usr/bin/ffmpeg` (platform-native apt build)
     + apt ffmpeg in the e2e job; Vercel/local untouched. ✅ **chosen**
     — prod's imageio binary is already proven live, and CI gets a binary
     that runs on its OS.
  2. Bump/change the `imageio-ffmpeg` pin — ✗ rejected: no evidence any
     version fixes the runner crash, and it risks the *working* prod pin.
  3. Skip ffmpeg-dependent tests in CI — ✗ rejected: deletes the exact
     coverage that caught this failure class.
- **Fix:** job-level `env.FFMPEG_PATH` in both CI jobs, apt ffmpeg in the
  e2e job, diagnostic step pushed as `f80a936`.
- **Retest:** five consecutive green CI runs on `main` (39042871812,
  39042984582, 39043668899, 39044122482, 39044903089) — backend + e2e
  jobs both pass; the weekly yt-dlp workflow was aligned in `8bf473c`.
  Node 20 deprecation annotations remain until the pending Dependabot
  action-bump PRs merge; runners migrate to Ubuntu 26 on 2026-10-19.

### F9 — vercel.json `headers`/`redirects` were silently ignored (and the fix's own outage)

- **Symptom A:** probing extensionless legal URLs showed `/about` → 404
  and — worse — **every static response had been missing all security
  headers** (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy`, `X-Powered-By`) since the first deploy. API
  responses only *looked* protected because FastAPI's own middleware adds
  those.
- **Diagnosis A (real evidence):** the project used legacy `builds` +
  `routes`; live probes showed the top-level `headers`/`redirects` arrays
  never applied (headers ABSENT on `/` and `/sw.js`; `/about` 404, no
  `Location`). With legacy `builds`, routing comes exclusively from
  `routes` — the modern top-level properties are ignored.
- **Symptom B (the attempted fix's outage):** moving headers/redirects
  *into* the legacy `routes` table (`bd45372`) **404'd every `/api/*`**
  (platform `NOT_FOUND`) for ~15 minutes.
- **Diagnosis B (real evidence):** on that deployment the first
  headers-only entry `{"src":"/(.*)","headers":{…}}` applied its headers
  to every response, but entries 2–16 never ran: `/sw.js` lacked its own
  entry's headers, `/about` had no `Location`, `/api/health` 404 while
  `/api/index.py` (the build output's default path) answered
  `{"detail":"Not Found"}` — legacy **headers-only route entries are
  terminal** (apply → default serve), so a leading one swallows every
  dest/redirect entry. Static filesystem hits are served by
  `handle: filesystem`, which cannot carry headers — so legacy routes
  fundamentally cannot header static responses.
- **Alternatives:**
  1. Modern vercel.json — drop `builds`, use `rewrites`
     (`/api/(.*)` → `/api/index`), explicit
     `functions.maxDuration: 300`, top-level `headers` + `redirects`.
     ✅ **chosen** — all properties documented to work without `builds`,
     and it could be validated on a **preview deployment first** so
     production was never the test bed.
  2. Attach headers to each dest entry in legacy routes — ✗ rejected:
     `handle: filesystem` hits (every static file) can never carry
     headers — dead end proven by B.
  3. `<meta http-equiv>` headers in HTML — ✗ rejected: nosniff and
     Permissions-Policy are unsupported via meta; they must be real
     response headers.
- **Preview-testing mechanics:** previews sit behind Vercel SSO
  (`ssoProtection: {"deploymentType":"all_except_custom_domains"}` —
  production's custom domain is exempt, which is why the site stayed
  public). A wrapper temporarily set `ssoProtection: null` through the
  project REST API, ran the battery, and **restored the exact value in a
  `finally` block**. (First run had a sentinel bug — `null` *is* the valid
  "disabled" value yet was treated as failure **and** restoration sat
  outside the `try`; v2 fixed both and the restored setting was verified
  as `{"deploymentType":"all_except_custom_domains"}`.)
- **Fix:** `b8d3ed5` reverted the broken legacy attempt first (restore
  service), then `0dfa478` landed the modern config.
- **Retest:** preview **13/13** and production **13/13** (home + all
  static security headers, 308 extensionless redirects, API via rewrite,
  IG info, MP3 1.22 MB download, sw.js/manifest headers,
  platforms=instagram-only, validation error schema).

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

---

## 7. Pivot: all-in-one → Instagram-dedicated + claymorphism redesign

Originally the app enabled both Instagram and YouTube. Live production testing
(see **F4** above) proved YouTube **cannot** be reliably extracted from any free
serverless host — Google's automated-traffic check blocks every datacenter IP,
and every legitimate mitigation (official player clients) failed. The only
workarounds (residential proxies, cookies, PO-token browser automation) are all
explicitly forbidden by the project's hard rules. Rather than ship a
half-broken multi-platform promise or fake results, the product was refocused.

**Decision:** make IGDesk a **single-platform (Instagram) tool** and remove
YouTube + every "coming soon" placeholder entirely.

- `backend/platforms.py`: registry now holds **only** Instagram; the
  `MEDIA_CDN_DOMAINS` SSRF allowlist was tightened to Instagram/Meta CDNs
  (`cdninstagram.com`, `fbcdn.net`) — a smaller, safer surface.
- `backend/config.py`: dropped the now-dead `youtube_player_clients` setting.
- `backend/extractor.py`: `_ydl_opts()` no longer carries the YouTube
  `extractor_args` branch.
- Tests (`test_unit`, `test_negative`, `test_integration`, `e2e/ui.spec.js`)
  were re-scoped to Instagram real-links; YouTube now asserts
  `UNSUPPORTED_PLATFORM`.
- Static pages (about/FAQ), manifest and PWA shortcuts de-mention YouTube.

**Alternatives considered:**
1. Keep YouTube enabled-but-broken behind a "coming soon"/error message.
   ✗ rejected — a paid-looking product shouldn't advertise a dead platform.
2. Keep the multi-platform registry but auto-disable YouTube on datacenter IPs.
   ✗ rejected — adds complexity for zero user value; the registry is now
   single-entry and trivially extensible if a platform ever becomes viable.
3. Instagram-only, tightest allowlist, extensible registry shape. ✅ **chosen**
   — honest, simplest to reason about, smallest SSRF surface, and the shape
   (`Platform` dataclass + `_BY_DOMAIN`) still supports adding a platform by
   appending one entry.

**UI redesign (same change-set):** rebuilt the frontend on a **claymorphism**
design language — Instagram-gradient accents, soft extruded double-shadows,
floating animated background blobs, sliding tab indicator, bouncy
micro-interactions, success confetti, reveal-on-scroll, and a light/dark clay
theme. Kept all accessibility constraints (>=44px targets, contrast, ARIA,
`prefers-reduced-motion`).
