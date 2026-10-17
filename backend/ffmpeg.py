"""ffmpeg discovery and safe subprocess streaming.

The binary is resolved in this order:

1. ``FFMPEG_PATH`` environment variable (never hardcoded)
2. the ``imageio-ffmpeg`` wheel, which ships a pinned static ffmpeg build
   inside the Python bundle (this is how ffmpeg reaches Vercel Functions)
3. ``ffmpeg`` on PATH (local development)

Media is streamed straight out of ffmpeg's stdout pipe — no intermediate
files are written for the merge / MP3 paths.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Iterator, List, Optional

from .config import settings
from .errors import AppError, ErrorCode

log = logging.getLogger(__name__)

_cached_exe: Optional[str] = None


def find_ffmpeg() -> Optional[str]:
    """Locate a usable ffmpeg binary, or ``None`` if unavailable."""
    global _cached_exe
    if _cached_exe:
        return _cached_exe

    env_path = os.getenv("FFMPEG_PATH")
    if env_path and os.path.isfile(env_path):
        _cached_exe = env_path
        return _cached_exe

    try:
        import imageio_ffmpeg  # type: ignore

        _cached_exe = imageio_ffmpeg.get_ffmpeg_exe()
        return _cached_exe
    except Exception:  # noqa: BLE001 - fall through to PATH lookup
        pass

    which = shutil.which("ffmpeg")
    if which:
        _cached_exe = which
    return _cached_exe


def ffmpeg_available() -> bool:
    """True when a usable ffmpeg binary was found."""
    return find_ffmpeg() is not None


def _streaming_container_args(video_ext: str) -> List[str]:
    """Container flags for writing to a non-seekable pipe.

    Fragmented MP4 (or native WebM) so the output is playable even though the
    moov atom can never be rewritten at the end of a seekable file.
    """
    if video_ext in ("webm", "mkv"):
        return ["-f", "webm"]
    return ["-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-f", "mp4"]


def stream_merged(video_url: str, audio_url: str, video_ext: str, audio_ext: str,
                  headers: Optional[dict] = None) -> Iterator[bytes]:
    """Merge a video-only + audio-only pair, yielding output chunks.

    Uses stream copy (no re-encode).  The process is terminated as soon as
    the generator is closed (client disconnect) or the time budget expires.
    """
    exe = find_ffmpeg()
    if not exe:
        raise AppError(ErrorCode.INTERNAL, "Media processing is unavailable on this server.")

    hdr_arg = ""
    if headers:
        hdr_arg = "".join(f"{k}: {v}\r\n" for k, v in headers.items())

    cmd: List[str] = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-user_agent", (headers or {}).get("User-Agent", "Mozilla/5.0"),
    ]
    if hdr_arg:
        cmd += ["-headers", hdr_arg]
    cmd += [
        "-i", video_url,
        "-user_agent", (headers or {}).get("User-Agent", "Mozilla/5.0"),
    ]
    if hdr_arg:
        cmd += ["-headers", hdr_arg]
    cmd += [
        "-i", audio_url,
        "-c", "copy",
        *_streaming_container_args(video_ext),
        "pipe:1",
    ]
    return _popen_stream(cmd)


def stream_mp3(audio_url: str, kbps: int, headers: Optional[dict] = None) -> Iterator[bytes]:
    """Transcode *audio_url* to MP3 at *kbps*, yielding output chunks."""
    exe = find_ffmpeg()
    if not exe:
        raise AppError(ErrorCode.INTERNAL, "MP3 conversion is unavailable on this server.")
    if kbps not in (128, 192, 320):
        raise AppError(ErrorCode.INVALID_URL, "Unsupported MP3 bitrate.")

    hdr_arg = "".join(f"{k}: {v}\r\n" for k, v in (headers or {}).items())
    cmd: List[str] = [
        exe, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-user_agent", (headers or {}).get("User-Agent", "Mozilla/5.0"),
    ]
    if hdr_arg:
        cmd += ["-headers", hdr_arg]
    cmd += [
        "-i", audio_url,
        "-vn", "-map", "0:a:0",
        "-codec:a", "libmp3lame", "-b:a", f"{kbps}k",
        "-f", "mp3", "pipe:1",
    ]
    return _popen_stream(cmd)


def _popen_stream(cmd: List[str]) -> Iterator[bytes]:
    """Run *cmd* and yield its stdout in chunks, killing it on early exit."""
    budget = settings.job_budget_seconds
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        log.error("ffmpeg spawn failed: %s", type(exc).__name__)
        raise AppError(ErrorCode.INTERNAL, "Could not start the media processor.") from exc

    assert proc.stdout is not None
    try:
        while True:
            chunk = proc.stdout.read(settings.chunk_size)
            if not chunk:
                break
            yield chunk
    except GeneratorExit:
        # Client disconnected — stop burning CPU/bandwidth.
        proc.kill()
        raise
    finally:
        try:
            if proc.poll() is None:
                proc.kill()
            stderr_tail = b""
            if proc.stderr is not None:
                stderr_tail = proc.stderr.read(2048)
            proc.wait(timeout=10)
            if proc.returncode not in (0, -9, 255) and stderr_tail:
                # -9/255 are our own kills; anything else may be a real failure.
                log.warning("ffmpeg exit %s: %s", proc.returncode, stderr_tail.decode(errors="replace")[:300])
        except Exception:  # noqa: BLE001 - cleanup must never raise
            pass
