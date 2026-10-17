"""Media pipeline: direct URL, streaming proxy, and ffmpeg merge/convert.

Implements the three-tier strategy from DECISIONS.md:

* **A — Direct**: when the upstream URL is client-usable and already carries
  ``Content-Disposition: attachment`` (a few CDNs do), redirect the browser
  straight to it. Zero bandwidth on our server.
* **B — Streaming proxy**: otherwise stream bytes from the CDN through the
  backend in chunks, forwarding ``Range`` headers for seeking, without ever
  writing the media to disk. Enforces max-size and time budgets.
* **C — Merge / convert**: 1080p+ YouTube (and 720p+ Instagram Reels) ship as
  separate video-only + audio-only streams; ``ffmpeg`` merges them (stream
  copy, no re-encode) into a fragmented MP4 streamed from a pipe. MP3
  requests transcode audio-only through the same pipe.

Every path validates the media host against the CDN allowlist before any
outbound request (SSRF re-check on the resolved URL, not just the user URL).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterator, Optional

import requests

from .config import settings
from .errors import AppError, ErrorCode
from .ffmpeg import stream_merged, stream_mp3
from .validation import validate_media_host

log = logging.getLogger(__name__)

# Headers that many CDNs require; yt-dlp supplies per-format values which the
# caller passes through as `headers`.
_UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36")


@dataclass
class UpstreamHead:
    """Result of a cheap HEAD/Range probe against a media URL."""

    status: int
    content_length: Optional[int]
    content_type: Optional[str]
    accepts_ranges: bool
    has_attachment: bool


def probe(url: str, headers: Optional[dict] = None) -> UpstreamHead:
    """Probe a media URL without downloading it (HEAD, fall back to 0-byte GET)."""
    validate_media_host(url)
    hdrs = {"User-Agent": _UA, **(headers or {})}
    try:
        resp = requests.head(url, headers=hdrs, allow_redirects=True,
                             timeout=settings.probe_timeout)
        if resp.status_code in (403, 405, 501):
            # Some CDNs reject HEAD; try a 1-byte GET instead.
            hdrs2 = {**hdrs, "Range": "bytes=0-0"}
            resp = requests.get(url, headers=hdrs2, stream=True,
                                timeout=settings.probe_timeout)
            resp.close()
    except requests.Timeout as exc:
        raise AppError(ErrorCode.TIMEOUT, "The media server timed out.") from exc
    except requests.RequestException as exc:
        log.warning("probe failed: %s", type(exc).__name__)
        raise AppError(ErrorCode.UPSTREAM_BLOCKED, "Could not reach the media server.") from exc

    cd = (resp.headers.get("Content-Disposition") or "").lower()
    ar = (resp.headers.get("Accept-Ranges") or "").lower()
    clen: Optional[int] = None
    raw_len = resp.headers.get("Content-Length")
    if raw_len and raw_len.isdigit():
        clen = int(raw_len)
    # A 206 response to a range probe reports the total in Content-Range.
    crange = resp.headers.get("Content-Range")
    if crange and "/" in crange:
        total = crange.rsplit("/", 1)[-1]
        if total.isdigit():
            clen = int(total)
    return UpstreamHead(
        status=resp.status_code,
        content_length=clen,
        content_type=resp.headers.get("Content-Type"),
        accepts_ranges=(ar == "bytes" or resp.status_code == 206),
        has_attachment="attachment" in cd,
    )


def check_size(content_length: Optional[int], kind: str) -> None:
    """Raise TOO_LARGE when a known size exceeds the configured limit."""
    limit = settings.max_file_bytes
    if content_length is not None and content_length > limit:
        raise AppError(
            ErrorCode.TOO_LARGE,
            f"This file is larger than the {limit // (1024 * 1024)} MB limit.",
        )


def proxy_stream(url: str, headers: Optional[dict] = None,
                 range_header: Optional[str] = None) -> Iterator[bytes]:
    """Yield media bytes from *url*, forwarding an optional Range request."""
    validate_media_host(url)
    hdrs = {"User-Agent": _UA, **(headers or {})}
    if range_header:
        hdrs["Range"] = range_header
    try:
        resp = requests.get(url, headers=hdrs, stream=True, timeout=settings.upstream_connect_timeout)
    except requests.Timeout as exc:
        raise AppError(ErrorCode.TIMEOUT, "The media server timed out.") from exc
    except requests.RequestException as exc:
        log.warning("proxy fetch failed: %s", type(exc).__name__)
        raise AppError(ErrorCode.UPSTREAM_BLOCKED, "Could not fetch the media.") from exc

    if resp.status_code in (403, 401):
        resp.close()
        raise AppError(ErrorCode.UPSTREAM_BLOCKED, "The media server refused the request.")
    if resp.status_code == 404:
        resp.close()
        raise AppError(ErrorCode.PRIVATE_OR_REMOVED, "The media file is no longer available.")
    if resp.status_code == 429:
        resp.close()
        raise AppError(ErrorCode.RATE_LIMITED, "The media server is rate limiting requests.")
    if resp.status_code >= 400:
        resp.close()
        raise AppError(ErrorCode.UPSTREAM_BLOCKED, "The media server returned an error.")

    limit = settings.max_file_bytes
    sent = 0
    try:
        for chunk in resp.iter_content(chunk_size=settings.chunk_size):
            if not chunk:
                break
            sent += len(chunk)
            if sent > limit:
                log.warning("stream aborted: exceeded size budget")
                break
            yield chunk
    finally:
        resp.close()


def proxied_headers(upstream: UpstreamHead, content_type: Optional[str]) -> Dict[str, str]:
    """Headers for a proxied response."""
    out: Dict[str, str] = {}
    ctype = content_type or (upstream.content_type if upstream else None) or "application/octet-stream"
    out["Content-Type"] = ctype
    if upstream and upstream.accepts_ranges:
        out["Accept-Ranges"] = "bytes"
    return out


def merge_stream(video_url: str, audio_url: str, video_ext: str, audio_ext: str,
                 headers: Optional[dict] = None) -> Iterator[bytes]:
    """Stream a merged (video+audio) fragmented MP4 from ffmpeg's stdout."""
    validate_media_host(video_url)
    validate_media_host(audio_url)
    return stream_merged(video_url, audio_url, video_ext, audio_ext, headers=headers)


def mp3_stream(audio_url: str, kbps: int, headers: Optional[dict] = None) -> Iterator[bytes]:
    """Stream an MP3 transcode of *audio_url* from ffmpeg's stdout."""
    validate_media_host(audio_url)
    return stream_mp3(audio_url, kbps, headers=headers)
