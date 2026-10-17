"""Integration tests against real public Instagram media links.

These verify the full pipeline end-to-end: metadata extraction, real file
downloads (video with audio, MP3, native audio, thumbnail), and ffprobe
validation that downloaded files are genuinely playable with correct duration.

Run with:  pytest -m integration
Skipped automatically when ffprobe/network is unavailable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import pytest
import requests

BASE = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000")

# Real, public, stable Instagram test links.
IG_REEL = "https://www.instagram.com/reel/DN035iN2Dum/"        # public reel (~30s)
IG_REEL_2 = "https://www.instagram.com/reel/DUP79qUCXs0/"      # second public reel

FFPROBE = shutil.which("ffprobe")
pytestmark = pytest.mark.integration

if not FFPROBE:
    pytest.skip("ffprobe not found — install ffmpeg to run integration tests",
                allow_module_level=True)


def _info(url: str) -> dict:
    r = requests.post(f"{BASE}/api/info", json={"url": url}, timeout=60)
    r.raise_for_status()
    data = r.json()
    assert "error" not in data, data
    return data


def _download(url: str, format_id: str, kind: str) -> requests.Response:
    r = requests.get(f"{BASE}/api/download",
                     params={"url": url, "format_id": format_id, "kind": kind},
                     timeout=300, stream=True)
    return r


def _save(resp: requests.Response) -> str:
    """Stream a response to a temp file, enforcing sanity size bounds."""
    fd, path = tempfile.mkstemp(suffix=".bin")
    os.close(fd)
    total = 0
    with open(path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                fh.write(chunk)
                total += len(chunk)
                assert total < 300 * 1024 * 1024, "download exceeded 300MB test bound"
    assert total > 1024, f"file too small ({total} bytes) — likely an error payload"
    return path


def _probe_streams(path: str) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "stream=codec_type,codec_name:format=duration",
         "-of", "json", path],
        capture_output=True, text=True, timeout=60,
    )
    import json
    return json.loads(out.stdout or "{}")


def _cleanup(*paths):
    for p in paths:
        if p and os.path.exists(p):
            os.unlink(p)


# ---------------------------------------------------------------------------
# /api/info
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("url,label", [
    (IG_REEL, "instagram_reel"),
    (IG_REEL_2, "instagram_reel_2"),
])
def test_info_real_links(url, label):
    d = _info(url)
    assert d["title"], label
    assert d["uploader"], label
    assert d["platform"]["key"] == "instagram"
    assert d["duration_seconds"] and d["duration_seconds"] > 0
    assert d["thumbnail_url"]
    # must offer at least one video and one audio/mp3 option
    assert d["video_options"], f"{label}: no video options"
    assert any(o["kind"] == "mp3" for o in d["audio_options"]), f"{label}: no MP3 option"


# ---------------------------------------------------------------------------
# Video download (must contain BOTH video and audio streams + real duration)
# ---------------------------------------------------------------------------
def test_video_download_has_video_audio_and_duration():
    d = _info(IG_REEL)
    # pick the highest listed quality to exercise the merge path
    fmt = d["video_options"][0]
    resp = _download(IG_REEL, fmt["id"], "video")
    assert resp.status_code == 200, resp.status_code
    path = _save(resp)
    try:
        probe = _probe_streams(path)
        types = {s.get("codec_type") for s in probe.get("streams", [])}
        assert "video" in types, f"no video stream: {types}"
        assert "audio" in types, f"no audio stream: {types}"
        # Regression guard for the "00:00 in galleries" bug: merged MP4s must
        # carry real duration metadata (faststart moov at front), not 0.
        dur = float(probe.get("format", {}).get("duration") or 0)
        assert dur > 0, "downloaded video reports 0 duration (missing moov)"
    finally:
        _cleanup(path)


def test_video_download_second_reel():
    d = _info(IG_REEL_2)
    fmt = d["video_options"][0]
    resp = _download(IG_REEL_2, fmt["id"], "video")
    assert resp.status_code == 200
    path = _save(resp)
    try:
        types = {s.get("codec_type") for s in _probe_streams(path).get("streams", [])}
        assert "video" in types and "audio" in types
    finally:
        _cleanup(path)


# ---------------------------------------------------------------------------
# MP3 conversion
# ---------------------------------------------------------------------------
def test_mp3_download_plays_and_duration_matches():
    d = _info(IG_REEL)
    mp3 = next(o for o in d["audio_options"] if o["kind"] == "mp3")
    resp = _download(IG_REEL, mp3["id"], "mp3")
    assert resp.status_code == 200
    path = _save(resp)
    try:
        probe = _probe_streams(path)
        fmt = probe.get("format", {})
        streams = probe.get("streams", [])
        assert any(s.get("codec_type") == "audio" for s in streams), "MP3 has no audio"
        codec = next((s.get("codec_name") for s in streams if s.get("codec_type") == "audio"), "")
        assert codec == "mp3", f"expected mp3 codec, got {codec}"
        # duration must be close to the source within tolerance
        dur = float(fmt.get("duration") or 0)
        src = d["duration_seconds"]
        assert abs(dur - src) <= 4, f"duration mismatch: {dur} vs {src}"
    finally:
        _cleanup(path)


# ---------------------------------------------------------------------------
# Native audio
# ---------------------------------------------------------------------------
def test_native_audio_download():
    d = _info(IG_REEL)
    native = next((o for o in d["audio_options"] if o["kind"] == "audio"), None)
    if native is None:
        pytest.skip("no native audio option for this reel")
    resp = _download(IG_REEL, native["id"], "audio")
    assert resp.status_code == 200
    path = _save(resp)
    try:
        streams = _probe_streams(path).get("streams", [])
        assert any(s.get("codec_type") == "audio" for s in streams)
    finally:
        _cleanup(path)


# ---------------------------------------------------------------------------
# Thumbnail
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("t", ["jpg", "png", "webp"])
def test_thumbnail_is_valid_image(t):
    r = requests.get(f"{BASE}/api/thumb", params={"url": IG_REEL, "type": t}, timeout=60)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert len(r.content) > 1000
    # verify magic bytes per format
    head = r.content[:16]
    if t == "jpg":
        assert head[:3] == b"\xff\xd8\xff", "not a JPEG"
    elif t == "png":
        assert head[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    elif t == "webp":
        assert head[:4] == b"RIFF" and head[8:12] == b"WEBP", "not a WEBP"


# ---------------------------------------------------------------------------
# Filename quality (Content-Disposition must be clean)
# ---------------------------------------------------------------------------
def test_download_filename_is_clean():
    d = _info(IG_REEL)
    fmt = d["video_options"][0]
    resp = _download(IG_REEL, fmt["id"], "video")
    cd = resp.headers.get("Content-Disposition", "")
    resp.close()
    assert cd.startswith("attachment;"), cd
    assert "filename*=UTF-8''" in cd
    # no path separators or reserved chars in the extracted name
    import re
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
    assert m
    from urllib.parse import unquote
    name = unquote(m.group(1))
    assert "/" not in name and "\\" not in name and '"' not in name


# ---------------------------------------------------------------------------
# Registry discipline — every enabled platform must have real-link coverage.
# ---------------------------------------------------------------------------
def test_every_enabled_platform_has_real_link_coverage():
    """Ensures each enabled platform has a real-link integration test.

    IGDesk is Instagram-only; if a platform is ever re-enabled in
    backend/platforms.py, a matching test must be added here first.
    """
    from backend.platforms import PLATFORMS
    enabled = {p.key for p in PLATFORMS if p.enabled}
    covered = {"instagram"}  # keys covered by tests above
    missing = enabled - covered
    assert not missing, (
        f"Enabled platforms without a real-link integration test: {sorted(missing)}. "
        "Add a test before enabling them."
    )
