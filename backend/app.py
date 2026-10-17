"""IGDesk Downloader — FastAPI application.

Single ASGI app deployed as one Vercel Function.  Routes:

* ``POST  /api/info``      — metadata + available formats for a URL
* ``GET   /api/download``  — deliver video / native audio / MP3
* ``GET   /api/thumb``     — deliver the best thumbnail as jpg/png/webp
* ``GET   /api/health``    — liveness + capability probe
* ``GET   /api/platforms`` — platform registry for the UI

Every error response uses the schema ``{"error": {"code", "message"}}``.
No user URL or file is ever persisted; logs contain hosts and codes only.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import time
from typing import Dict, Iterator, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import requests

from . import pipeline
from .config import PROJECT_NAME, PROJECT_VERSION, settings
from .errors import AppError, ErrorCode
from .extractor import MediaInfo, extract_info, map_download_error
from .ffmpeg import ffmpeg_available, find_ffmpeg
from .filenames import build_filename, content_disposition
from .platforms import public_platform_list
from .validation import validate_and_detect

try:
    import yt_dlp
    _YTDL_VERSION = getattr(yt_dlp.version, "__version__", "unknown")
except Exception:  # pragma: no cover
    _YTDL_VERSION = "unavailable"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("igdesk")

app = FastAPI(title=PROJECT_NAME, version=PROJECT_VERSION, docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    max_age=600,
)

# ---------------------------------------------------------------------------
# Security headers (applies to API responses; static pages get theirs from
# vercel.json)
# ---------------------------------------------------------------------------
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


@app.middleware("http")
async def security_headers_and_limits(request: Request, call_next):
    if not await _rate_limit(request):
        return JSONResponse(
            status_code=429,
            content={"error": {"code": ErrorCode.RATE_LIMITED,
                               "message": "Too many requests. Please wait a moment."}},
            headers={"Retry-After": "30", **_SECURITY_HEADERS},
        )
    response = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


# ---------------------------------------------------------------------------
# Best-effort per-IP rate limiting (in-memory; per warm serverless instance)
# ---------------------------------------------------------------------------
_buckets: Dict[str, Tuple[float, int]] = {}


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _rate_limit(request: Request) -> bool:
    path = request.url.path
    if path in ("/api/health", "/api/platforms"):
        return True
    limit = settings.rate_limit_info_per_min
    if path.startswith("/api/download"):
        limit = settings.rate_limit_download_per_min
    elif path.startswith("/api/thumb"):
        limit = settings.rate_limit_thumb_per_min

    key = f"{_client_ip(request)}:{path.rsplit('/', 1)[-1]}"
    now = time.time()
    window, count = _buckets.get(key, (now, 0))
    if now - window >= 60:
        window, count = now, 0
    count += 1
    _buckets[key] = (window, count)
    if len(_buckets) > 10_000:  # bound memory on a long-lived instance
        _buckets.clear()
    return count <= limit


# ---------------------------------------------------------------------------
# Info cache (per instance, short TTL) — avoids re-extracting for downloads
# ---------------------------------------------------------------------------
_info_cache: Dict[str, Tuple[float, MediaInfo]] = {}


def _cached_info(url: str, platform) -> MediaInfo:
    key = hashlib.sha256(url.encode()).hexdigest()
    now = time.time()
    hit = _info_cache.get(key)
    if hit and now - hit[0] < settings.info_cache_ttl:
        return hit[1]
    info = extract_info(url, platform)
    _info_cache[key] = (now, info)
    if len(_info_cache) > 64:
        _info_cache.clear()
    return info


def _error(exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=exc.to_payload())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
class InfoRequest(BaseModel):
    """POST /api/info body."""

    url: str


@app.get("/api/health")
def health() -> dict:
    """Liveness + capability probe (no secrets, no user data)."""
    return {
        "status": "ok",
        "service": PROJECT_NAME,
        "version": PROJECT_VERSION,
        "yt_dlp_version": _YTDL_VERSION,
        "ffmpeg_available": ffmpeg_available(),
        "host": os.getenv("VERCEL_REGION") or "local",
    }


@app.get("/api/platforms")
def platforms() -> dict:
    """Platform registry: enabled platforms + coming-soon entries."""
    return {"platforms": public_platform_list()}


@app.post("/api/info")
def info(payload: InfoRequest) -> dict:
    """Validate a URL and return metadata + available download options."""
    try:
        url, platform = validate_and_detect(payload.url)
        media = _cached_info(url, platform)
        return media.to_dict()
    except AppError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001
        log.exception("info: unexpected error")
        return _error(AppError(ErrorCode.INTERNAL, "Something went wrong. Please try again."))


# ---------------------------------------------------------------------------
# Download resolution helpers
# ---------------------------------------------------------------------------
def _find_format(media: MediaInfo, fmt_id: str):
    for opt in (*media.video_options, *media.audio_options):
        if opt.id == fmt_id:
            return opt
    raise AppError(ErrorCode.INVALID_URL, "Unknown format id.")


def _raw_format_map(ydl_info: dict) -> dict:
    return {str(f.get("format_id")): f for f in (ydl_info.get("formats") or [])}


def _extract_raw(url: str) -> dict:
    """Re-extract with yt-dlp to obtain fresh signed media URLs."""
    from .extractor import _ydl_opts  # reuse hardened options

    import yt_dlp as _y
    try:
        with _y.YoutubeDL(_ydl_opts()) as ydl:
            return ydl.extract_info(url, download=False) or {}
    except Exception as exc:  # noqa: BLE001
        raise map_download_error(exc) from exc


@app.get("/api/download")
def download(url: str, format_id: str, kind: str, request: Request):
    """Deliver the requested media file.

    ``kind`` is one of ``video`` | ``audio`` | ``mp3``.  The response is a
    chunked stream (merge/MP3 paths) or a proxied/redirected byte stream.
    """
    try:
        norm_url, platform = validate_and_detect(url)
        if kind not in ("video", "audio", "mp3"):
            raise AppError(ErrorCode.INVALID_URL, "Invalid download kind.")

        media = _cached_info(norm_url, platform)
        opt = _find_format(media, format_id)

        # Fresh signed URLs (the cached info may hold stale signatures).
        raw = _extract_raw(norm_url)
        raw_formats = _raw_format_map(raw)

        filename = build_filename(media.title, media.media_id, opt.ext,
                                  prefix="" if kind != "mp3" else "")
        disposition = content_disposition(filename)

        # ---------------- MP3 ------------------------------------------------
        if kind == "mp3" or opt.kind == "mp3":
            kbps = opt.bitrate_kbps or 192
            src = _best_audio_raw(raw_formats, prefer_ext=("m4a", "mp4", "webm"))
            if src is None:
                raise AppError(ErrorCode.PRIVATE_OR_REMOVED, "No audio stream is available.")
            stream = pipeline.mp3_stream(src["url"], kbps, headers=src.get("http_headers"))
            fname = build_filename(media.title, media.media_id, "mp3")
            return StreamingResponse(
                _guarded(stream),
                media_type="audio/mpeg",
                headers={"Content-Disposition": content_disposition(fname),
                         "X-Content-Type-Options": "nosniff"},
            )

        # ---------------- Native audio --------------------------------------
        if kind == "audio":
            raw_fmt = raw_formats.get(opt.id.split(":", 1)[1]) if ":" in opt.id else None
            if not raw_fmt or not raw_fmt.get("url"):
                raise AppError(ErrorCode.PRIVATE_OR_REMOVED, "This audio stream is unavailable.")
            head = pipeline.probe(raw_fmt["url"], headers=raw_fmt.get("http_headers"))
            pipeline.check_size(head.content_length, kind)
            if head.status in (200, 206) and head.has_attachment and settings.allow_direct_redirect:
                return RedirectResponse(raw_fmt["url"], status_code=302)
            stream = pipeline.proxy_stream(raw_fmt["url"], headers=raw_fmt.get("http_headers"))
            headers = pipeline.proxied_headers(head, f"audio/{opt.ext}")
            headers["Content-Disposition"] = content_disposition(
                build_filename(media.title, media.media_id, opt.ext))
            if head.content_length:
                headers["Content-Length"] = str(head.content_length)
            return StreamingResponse(_guarded(stream), headers=headers)

        # ---------------- Video ---------------------------------------------
        raw_fmt = raw_formats.get(opt.id.split(":", 1)[1]) if ":" in opt.id else None
        if not raw_fmt or not raw_fmt.get("url"):
            raise AppError(ErrorCode.PRIVATE_OR_REMOVED, "This video stream is unavailable.")

        has_both = raw_fmt.get("vcodec") not in (None, "none") and \
            raw_fmt.get("acodec") not in (None, "none")

        if has_both:
            head = pipeline.probe(raw_fmt["url"], headers=raw_fmt.get("http_headers"))
            pipeline.check_size(head.content_length, kind)
            if head.status in (200, 206) and head.has_attachment and settings.allow_direct_redirect:
                return RedirectResponse(raw_fmt["url"], status_code=302)
            stream = pipeline.proxy_stream(raw_fmt["url"], headers=raw_fmt.get("http_headers"))
            headers = pipeline.proxied_headers(head, "video/mp4")
            headers["Content-Disposition"] = content_disposition(
                build_filename(media.title, media.media_id, opt.ext))
            if head.content_length:
                headers["Content-Length"] = str(head.content_length)
            return StreamingResponse(_guarded(stream), headers=headers)

        # Video-only: merge with the best matching audio (1080p+ path).
        audio = _best_audio_raw(raw_formats, prefer_ext=("m4a", "mp4", "webm"))
        if audio is None:
            raise AppError(ErrorCode.PRIVATE_OR_REMOVED, "No audio stream is available to merge.")
        a_size = audio.get("filesize") or audio.get("filesize_approx")
        v_size = raw_fmt.get("filesize") or raw_fmt.get("filesize_approx")
        if a_size and v_size:
            pipeline.check_size(a_size + v_size, kind)
        merged_ext = "mp4" if opt.ext in ("mp4", "m4v") else opt.ext
        stream = pipeline.merge_stream(
            raw_fmt["url"], audio["url"],
            video_ext=merged_ext, audio_ext=audio.get("ext") or "m4a",
            headers=raw_fmt.get("http_headers"),
        )
        fname = build_filename(media.title, media.media_id, merged_ext)
        return StreamingResponse(
            _guarded(stream),
            media_type="video/mp4" if merged_ext == "mp4" else "application/octet-stream",
            headers={"Content-Disposition": content_disposition(fname),
                     "X-Content-Type-Options": "nosniff"},
        )

    except AppError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001
        log.exception("download: unexpected error")
        return _error(AppError(ErrorCode.INTERNAL, "Download failed. Please try again."))


def _best_audio_raw(raw_formats: dict, prefer_ext=("m4a", "mp4", "webm")) -> Optional[dict]:
    """Pick the best audio-only raw format, preferring *prefer_ext* order."""
    candidates = [
        f for f in raw_formats.values()
        if f.get("url") and f.get("acodec") not in (None, "none")
        and f.get("vcodec") in (None, "none")
    ]
    if not candidates:
        return None
    for ext in prefer_ext:
        tier = [f for f in candidates if f.get("ext") == ext]
        if tier:
            return max(tier, key=lambda f: f.get("abr") or 0)
    return max(candidates, key=lambda f: f.get("abr") or 0)


def _guarded(stream: Iterator[bytes]) -> Iterator[bytes]:
    """Wrap a stream so a client disconnect never leaks the generator."""
    try:
        yield from stream
    except AppError:
        log.warning("stream aborted by AppError")
    except Exception:  # noqa: BLE001
        log.exception("stream aborted unexpectedly")
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Thumbnail
# ---------------------------------------------------------------------------
_THUMB_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


@app.get("/api/thumb")
def thumb(url: str, type: str = "jpg"):  # noqa: A002 - query param name fixed by spec
    """Return the best thumbnail as jpg/png/webp."""
    try:
        if type not in _THUMB_TYPES:
            raise AppError(ErrorCode.INVALID_URL, "Thumbnail type must be jpg, png or webp.")
        norm_url, platform = validate_and_detect(url)
        media = _cached_info(norm_url, platform)
        if not media.thumbnail_url:
            raise AppError(ErrorCode.PRIVATE_OR_REMOVED, "No thumbnail is available.")

        data = _fetch_best_thumbnail(media)
        if len(data) > settings.max_thumbnail_bytes:
            raise AppError(ErrorCode.TOO_LARGE, "Thumbnail is too large.")

        if type != "jpg":
            data = _convert_image(data, type)

        fname = build_filename(media.title, media.media_id, type)
        return Response(
            content=data,
            media_type=_THUMB_TYPES[type],
            headers={"Content-Disposition": content_disposition(fname),
                     "X-Content-Type-Options": "nosniff"},
        )
    except AppError as exc:
        return _error(exc)
    except Exception:  # noqa: BLE001
        log.exception("thumb: unexpected error")
        return _error(AppError(ErrorCode.INTERNAL, "Thumbnail fetch failed."))


def _fetch_best_thumbnail(media: MediaInfo) -> bytes:
    """Return bytes for the best *reachable* thumbnail.

    Sources like YouTube frequently 404 their top-resolution variant
    (e.g. maxresdefault.jpg) while lower variants exist.  Candidates are
    tried highest-resolution-first and the first one that returns 2xx image
    bytes wins; each candidate is re-checked against the SSRF host allowlist.
    """
    from .validation import validate_media_host

    # Build a de-duplicated, best-first candidate list.
    candidates: list[str] = []
    for entry in sorted(
        media.thumbnails,
        key=lambda t: (t.get("width") or 0) * (t.get("height") or 0),
        reverse=True,
    ):
        if entry.get("url"):
            candidates.append(entry["url"])
    if media.thumbnail_url:
        candidates.append(media.thumbnail_url)

    seen: set[str] = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        try:
            validate_media_host(cand)
        except AppError:
            continue
        try:
            resp = requests.get(
                cand,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=settings.probe_timeout,
            )
        except requests.RequestException:
            continue
        if resp.status_code == 200 and resp.content and len(resp.content) > 500:
            return resp.content

    raise AppError(ErrorCode.UPSTREAM_BLOCKED, "Could not fetch the thumbnail.")


def _convert_image(data: bytes, target: str) -> bytes:
    """Convert image bytes to *target* using Pillow when available."""
    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise AppError(ErrorCode.INTERNAL, "Image conversion is unavailable.") from exc
    img = Image.open(io.BytesIO(data))
    buf = io.BytesIO()
    if target == "png":
        img.save(buf, format="PNG")
    else:
        img.save(buf, format="WEBP", quality=90)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Static assets (local dev convenience). On Vercel, static files in /public
# are served by the platform; this mount lets `python run.py` serve the whole
# site standalone. Guarded so it never shadows the /api routes above.
# ---------------------------------------------------------------------------
_PUBLIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
if os.path.isdir(_PUBLIC_DIR):
    app.mount("/", StaticFiles(directory=_PUBLIC_DIR, html=True), name="public")
