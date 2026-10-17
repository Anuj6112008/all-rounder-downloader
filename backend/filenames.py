"""Filename sanitisation for Content-Disposition headers.

Windows/macOS/Linux reserved characters and control codes are stripped, the
name is length-limited, and a platform/media-id suffix keeps names unique
and traceable without storing anything server-side.
"""
from __future__ import annotations

import re
import unicodedata

_RESERVED_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_MAX_STEM = 120


def sanitize_filename(name: str, max_stem: int = _MAX_STEM) -> str:
    """Return a filesystem-safe stem (no extension) derived from *name*."""
    name = unicodedata.normalize("NFKC", name or "")
    name = _RESERVED_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "download"
    if name.upper() in _WINDOWS_RESERVED:
        name = f"_{name}"
    if len(name) > max_stem:
        name = name[:max_stem].rstrip(" .")
    return name or "download"


def build_filename(title: str, media_id: str, ext: str, *, prefix: str = "") -> str:
    """Compose ``<title> [<id>].<ext>`` with every part sanitised."""
    stem = sanitize_filename(title)
    safe_id = sanitize_filename(media_id, max_stem=40) if media_id else ""
    safe_ext = re.sub(r"[^a-z0-9]", "", (ext or "").lower()) or "bin"
    safe_prefix = sanitize_filename(prefix, max_stem=20) if prefix else ""
    parts = [p for p in (safe_prefix, stem) if p]
    base = " ".join(parts)
    if safe_id:
        base = f"{base} [{safe_id}]"
    return f"{base}.{safe_ext}"


def content_disposition(filename: str) -> str:
    """Build a robust Content-Disposition value (ASCII fallback + UTF-8)."""
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "'")
    quoted = filename.replace('"', "%22")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"
