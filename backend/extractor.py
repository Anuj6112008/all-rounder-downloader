"""yt-dlp wrapper: metadata extraction and error mapping.

This module never writes media to disk and never logs full URLs.  All
yt-dlp interaction happens through the library API with hardened options
(``noplaylist``, ``socket_timeout``, cache confined to /tmp, no post-download
execution).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yt_dlp
from yt_dlp.utils import DownloadError, GeoRestrictedError

from .config import settings
from .errors import AppError, ErrorCode

log = logging.getLogger(__name__)


@dataclass
class FormatOption:
    """A single downloadable option rendered as a row in the UI."""

    id: str                       # opaque id passed back to /api/download
    kind: str                     # "video" | "audio" | "mp3" | "thumb"
    label: str                    # e.g. "1080p", "MP3 320 kbps", "M4A"
    ext: str                      # container/codec extension of the result
    height: Optional[int] = None
    fps: Optional[float] = None
    bitrate_kbps: Optional[int] = None
    filesize_bytes: Optional[int] = None
    note: str = ""                # e.g. "merged", "progressive", "native"


@dataclass
class MediaInfo:
    """Normalised metadata for one media item."""

    platform_key: str
    platform_name: str
    platform_icon: str
    media_id: str
    title: str
    uploader: str
    duration_seconds: Optional[int]
    thumbnail_url: str
    webpage_url: str
    video_options: List[FormatOption] = field(default_factory=list)
    audio_options: List[FormatOption] = field(default_factory=list)
    thumbnails: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for the JSON API."""
        def ser(o: FormatOption) -> Dict[str, Any]:
            return {k: v for k, v in o.__dict__.items() if v is not None}

        return {
            "platform": {
                "key": self.platform_key,
                "name": self.platform_name,
                "icon": self.platform_icon,
            },
            "id": self.media_id,
            "title": self.title,
            "uploader": self.uploader,
            "duration_seconds": self.duration_seconds,
            "thumbnail_url": self.thumbnail_url,
            "webpage_url": self.webpage_url,
            "video_options": [ser(o) for o in self.video_options],
            "audio_options": [ser(o) for o in self.audio_options],
            "thumbnails": self.thumbnails,
            "limits": {
                "max_file_bytes": settings.max_file_bytes,
                "max_duration_seconds": settings.max_duration_seconds,
            },
        }


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

_PRIVATE_RE = re.compile(
    r"private video|this video is private|sign in to confirm your age|"
    r"confirm you.?re not a bot|login required|members.?only|"
    r"this content is only available|register to view|"
    r"join this channel|age.restricted", re.IGNORECASE)
_GEO_RE = re.compile(
    r"available in your (?:country|region)|not available in your|"
    r"your country|geo.restricted|blocked in your country", re.IGNORECASE)
_UNAVAILABLE_RE = re.compile(
    r"video unavailable|content isn.?t available|removed|does not exist|"
    r"404|not found|has been removed|no longer available", re.IGNORECASE)
_RATE_RE = re.compile(r"too many requests|429|rate.limit", re.IGNORECASE)
_TIMEOUT_RE = re.compile(r"timed? ?out|timeout|took too long", re.IGNORECASE)


def map_download_error(exc: Exception) -> AppError:
    """Translate a yt-dlp exception into a user-safe :class:`AppError`."""
    if isinstance(exc, AppError):
        return exc
    text = str(exc)
    if isinstance(exc, GeoRestrictedError) or _GEO_RE.search(text):
        return AppError(ErrorCode.GEO_BLOCKED, "This media is restricted in this region.")
    if _PRIVATE_RE.search(text):
        return AppError(ErrorCode.LOGIN_REQUIRED, "This media needs a login. Only public content is supported.")
    if _UNAVAILABLE_RE.search(text):
        return AppError(ErrorCode.PRIVATE_OR_REMOVED, "This media is private, removed or unavailable.")
    if _RATE_RE.search(text):
        return AppError(ErrorCode.RATE_LIMITED, "The platform is rate limiting requests. Try again shortly.")
    if _TIMEOUT_RE.search(text):
        return AppError(ErrorCode.TIMEOUT, "The request timed out. Try again.")
    if isinstance(exc, DownloadError):
        return AppError(ErrorCode.UPSTREAM_BLOCKED, "The platform blocked this request. Try again later.")
    log.warning("unmapped extractor error: %s", type(exc).__name__)
    return AppError(ErrorCode.INTERNAL, "Something went wrong while reading this link.")


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _ydl_opts() -> Dict[str, Any]:
    """Hardened yt-dlp options (no playlists, quiet, timeouts, /tmp cache)."""
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": settings.socket_timeout,
        "retries": 1,
        "no_check_certificates": False,
        "geo_bypass": False,          # never attempt to spoof location
        "cachedir": os.path.join(settings.tmp_dir, "ytdlp-cache"),
        "noprogress": True,
        "ignore_no_formats_error": False,
        "color": "never",
    }


def extract_info(url: str, platform) -> MediaInfo:
    """Extract metadata for *url* and normalise it into :class:`MediaInfo`.

    Raises:
        AppError: mapped from yt-dlp failures, or TOO_LARGE when the media
            exceeds the configured duration limit.
    """
    try:
        with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
            raw = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001 - mapped centrally
        raise map_download_error(exc) from exc

    if not raw:
        raise AppError(ErrorCode.PRIVATE_OR_REMOVED, "No media found at this link.")

    formats = raw.get("formats") or []
    duration = raw.get("duration") or _infer_duration(formats)
    if duration and duration > settings.max_duration_seconds:
        raise AppError(
            ErrorCode.TOO_LARGE,
            f"This media is longer than the {settings.max_duration_seconds // 60} minute limit.",
        )

    video_opts, audio_opts = _build_options(formats, duration)

    thumbs = [
        {"url": t.get("url"), "width": t.get("width"), "height": t.get("height")}
        for t in (raw.get("thumbnails") or [])
        if t.get("url")
    ]
    if not thumbs and raw.get("thumbnail"):
        thumbs = [{"url": raw["thumbnail"], "width": None, "height": None}]

    return MediaInfo(
        platform_key=platform.key,
        platform_name=platform.name,
        platform_icon=platform.icon,
        media_id=str(raw.get("id") or ""),
        title=(raw.get("title") or "Untitled").strip(),
        uploader=(raw.get("uploader") or raw.get("channel") or "Unknown").strip(),
        duration_seconds=int(duration) if duration else None,
        thumbnail_url=thumbs[-1]["url"] if thumbs else "",
        webpage_url=raw.get("webpage_url") or url,
        video_options=video_opts,
        audio_options=audio_opts,
        thumbnails=thumbs,
    )


def _infer_duration(formats: list) -> int | None:
    """Best-effort duration recovery when the extractor omits it.

    Some platforms (notably Instagram) do not expose a top-level ``duration``
    field, but embed ``duration_s`` inside a base64 ``efg`` query parameter on
    their media URLs.  Returns seconds, or ``None`` if it cannot be recovered.
    """
    import base64
    import json
    import re
    from urllib.parse import unquote

    for f in formats:
        url = f.get("url") or ""
        if not url:
            continue
        m = re.search(r"[?&]efg=([^&]+)", url)
        if not m:
            continue
        try:
            blob = json.loads(base64.b64decode(unquote(m.group(1))).decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 - malformed param, just skip
            continue
        secs = blob.get("duration_s")
        if isinstance(secs, (int, float)) and secs > 0:
            return int(secs)
        if isinstance(f.get("duration"), (int, float)) and f["duration"] > 0:
            return int(f["duration"])
    return None


def _build_options(formats: List[dict], duration: Optional[int]):
    """Turn raw yt-dlp formats into deduped video/audio option lists."""
    video_rows: Dict[int, dict] = {}    # height -> best entry
    audio_rows: Dict[str, dict] = {}    # ext -> best entry

    for f in formats:
        if f.get("vcodec") in (None, "none") and f.get("acodec") in (None, "none"):
            continue
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        has_video = vcodec not in (None, "none")
        has_audio = acodec not in (None, "none")

        if has_video and has_audio:
            # Progressive (video+audio in one stream): good fallback quality.
            h = f.get("height") or 0
            cur = video_rows.get(h)
            if not cur or (f.get("tbr") or 0) > (cur.get("tbr") or 0):
                video_rows[h] = dict(f, _progressive=True)
        elif has_video:
            h = f.get("height") or 0
            cur = video_rows.get(h)
            if not cur or not cur.get("_progressive") or (f.get("tbr") or 0) > (cur.get("tbr") or 0):
                # keep video-only entry; merged audio is added later
                if not cur or (f.get("tbr") or 0) > (cur.get("tbr") or 0) or cur.get("_progressive"):
                    video_rows[h] = dict(f, _progressive=False)
        elif has_audio:
            ext = f.get("ext") or "m4a"
            cur = audio_rows.get(ext)
            if not cur or (f.get("abr") or 0) > (cur.get("abr") or 0):
                audio_rows[ext] = f

    best_audio = max(
        (f for f in audio_rows.values()),
        key=lambda f: f.get("abr") or 0,
        default=None,
    )

    video_opts: List[FormatOption] = []
    for h in sorted(video_rows, reverse=True):
        if not h:
            continue
        f = video_rows[h]
        progressive = bool(f.get("_progressive"))
        ext = f.get("ext") or "mp4"
        size = f.get("filesize") or f.get("filesize_approx")
        if size is None and duration and f.get("tbr"):
            size = int(f["tbr"] * 1000 / 8 * duration)
        note = "progressive (video+audio)" if progressive else "video — audio merged automatically"
        video_opts.append(
            FormatOption(
                id=f"v:{f.get('format_id')}",
                kind="video",
                label=f"{h}p",
                ext=ext,
                height=h,
                fps=f.get("fps"),
                filesize_bytes=int(size) if size else None,
                note=note,
            )
        )

    audio_opts: List[FormatOption] = []
    for ext, f in sorted(audio_rows.items(), key=lambda kv: -(kv[1].get("abr") or 0)):
        size = f.get("filesize") or f.get("filesize_approx")
        if size is None and duration and f.get("abr"):
            size = int(f["abr"] * 1000 / 8 * duration)
        label = ext.upper()
        if ext == "m4a":
            label = "M4A"
        elif ext == "webm":
            label = "WEBM (Opus)"
        audio_opts.append(
            FormatOption(
                id=f"a:{f.get('format_id')}",
                kind="audio",
                label=label,
                ext=ext,
                bitrate_kbps=int(f["abr"]) if f.get("abr") else None,
                filesize_bytes=int(size) if size else None,
                note="native audio",
            )
        )

    # MP3 conversion options (always available; ffmpeg converts at download time)
    for kbps in (320, 192, 128):
        size = int(kbps * 1000 / 8 * duration) if duration else None
        audio_opts.append(
            FormatOption(
                id=f"mp3:{kbps}",
                kind="mp3",
                label=f"MP3 {kbps} kbps",
                ext="mp3",
                bitrate_kbps=kbps,
                filesize_bytes=size,
                note="converted",
            )
        )

    if not video_opts and not audio_opts:
        raise AppError(ErrorCode.PRIVATE_OR_REMOVED, "No downloadable formats were found.")
    return video_opts, audio_opts
