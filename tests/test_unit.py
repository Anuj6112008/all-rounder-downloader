"""Unit tests: URL validation, SSRF blocking, platform detection,
error mapping, format selection, and filename sanitisation.

These run offline and fast — no network, no yt-dlp extraction.
"""
from __future__ import annotations

import pytest

from backend.errors import AppError, ErrorCode
from backend.filenames import build_filename, content_disposition, sanitize_filename
from backend.platforms import detect_platform, is_media_host
from backend.validation import normalize_url, validate_and_detect, validate_media_host


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------
class TestNormalizeUrl:
    def test_valid_https(self):
        url, host = normalize_url("https://www.youtube.com/watch?v=abc")
        assert host == "www.youtube.com"
        assert url.startswith("https://")

    def test_bare_domain_assumes_https(self):
        url, host = normalize_url("youtube.com/watch?v=abc")
        assert url == "https://youtube.com/watch?v=abc"

    def test_fragment_stripped(self):
        url, _ = normalize_url("https://youtu.be/abc#t=10")
        assert "#" not in url

    def test_too_long_rejected(self):
        with pytest.raises(AppError) as e:
            normalize_url("https://example.com/" + "a" * 600)
        assert e.value.code == ErrorCode.INVALID_URL

    def test_empty_rejected(self):
        for bad in ("", "   ", None):
            with pytest.raises(AppError) as e:
                normalize_url(bad)
            assert e.value.code == ErrorCode.INVALID_URL

    def test_non_http_scheme_rejected(self):
        for bad in ("ftp://youtube.com/a", "javascript:alert(1)", "file:///etc/passwd"):
            with pytest.raises(AppError) as e:
                normalize_url(bad)
            assert e.value.code == ErrorCode.INVALID_URL

    def test_embedded_credentials_rejected(self):
        with pytest.raises(AppError) as e:
            normalize_url("https://user:pass@youtube.com/watch?v=a")
        assert e.value.code == ErrorCode.INVALID_URL


# ---------------------------------------------------------------------------
# SSRF blocking
# ---------------------------------------------------------------------------
class TestSsrfBlocking:
    @pytest.mark.parametrize("url", [
        "http://localhost/api",
        "http://localhost:8000/api",
        "https://127.0.0.1/api",
        "http://0.0.0.0/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/modem",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://[::1]/",
        "http://metadata.google.internal/",
    ])
    def test_private_and_internal_blocked(self, url):
        with pytest.raises(AppError) as e:
            normalize_url(url)
        assert e.value.code == ErrorCode.INVALID_URL

    def test_media_host_rejects_private(self):
        with pytest.raises(AppError):
            validate_media_host("http://127.0.0.1/secret.mp4")

    def test_media_host_rejects_non_allowlisted(self):
        with pytest.raises(AppError):
            validate_media_host("https://evil.example.com/x.mp4")

    def test_media_host_allows_known_cdn(self):
        assert validate_media_host("https://scontent.xx.fbcdn.net/videoplayback?x=1")


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------
class TestPlatformDetection:
    def test_youtube_now_unsupported(self):
        # IGDesk is Instagram-only; YouTube must NOT be detected as a platform.
        assert detect_platform("www.youtube.com") is None
        assert detect_platform("youtu.be") is None

    def test_instagram(self):
        assert detect_platform("www.instagram.com").key == "instagram"
        assert detect_platform("instagr.am").key == "instagram"

    def test_subdomain_maps_to_platform(self):
        # a subdomain of a registered domain maps back to its platform
        assert detect_platform("staging.instagram.com").key == "instagram"

    def test_unknown_returns_none(self):
        assert detect_platform("evil.example.com") is None

    def test_enabled_platform_passes_validation(self):
        url, plat = validate_and_detect("https://www.instagram.com/reel/ABC123/")
        assert plat.key == "instagram"

    def test_other_platforms_rejected(self):
        # Only Instagram is enabled; other platforms are unsupported.
        with pytest.raises(AppError) as e:
            validate_and_detect("https://www.tiktok.com/@u/video/1")
        assert e.value.code == ErrorCode.UNSUPPORTED_PLATFORM

    def test_unlisted_domain_rejected(self):
        with pytest.raises(AppError) as e:
            validate_and_detect("https://evil.example.com/video")
        assert e.value.code == ErrorCode.UNSUPPORTED_PLATFORM

    def test_media_host_allowlist(self):
        assert is_media_host("instagram.fpnq7-1.fna.fbcdn.net")
        assert is_media_host("scontent.cdninstagram.com")
        assert not is_media_host("notchecked.example.com")


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------
class TestErrorMapping:
    def _map(self, msg):
        from backend.extractor import map_download_error
        return map_download_error(RuntimeError(msg)).code

    def test_private(self):
        assert self._map("Private video. Sign in to confirm your age") == ErrorCode.LOGIN_REQUIRED

    def test_removed(self):
        assert self._map("Video unavailable. This video has been removed") == ErrorCode.PRIVATE_OR_REMOVED

    def test_geo(self):
        assert self._map("The uploader has not made this video available in your country") == ErrorCode.GEO_BLOCKED

    def test_bot_check_maps_to_upstream_not_login(self):
        # A datacenter-IP bot check must NOT be reported as private/login.
        assert self._map("Sign in to confirm you're not a bot") == ErrorCode.UPSTREAM_BLOCKED
        assert self._map("Please confirm you're not a bot") == ErrorCode.UPSTREAM_BLOCKED

    def test_rate(self):
        assert self._map("HTTP Error 429: Too Many Requests") == ErrorCode.RATE_LIMITED

    def test_timeout(self):
        assert self._map("Connection timed out") == ErrorCode.TIMEOUT

    def test_passthrough_apperror(self):
        from backend.extractor import map_download_error
        orig = AppError(ErrorCode.TOO_LARGE, "big")
        assert map_download_error(orig) is orig


# ---------------------------------------------------------------------------
# Filename sanitisation
# ---------------------------------------------------------------------------
class TestFilenames:
    def test_strips_reserved_chars(self):
        assert '<>:"/\\|?*' not in sanitize_filename('a<b>c:d"e/f\\g|h?i*j')

    def test_windows_reserved_prefixed(self):
        assert sanitize_filename("CON").startswith("_")

    def test_empty_fallback(self):
        assert sanitize_filename("   ") == "download"
        assert sanitize_filename("///") == "download"

    def test_length_limited(self):
        assert len(sanitize_filename("x" * 500)) <= 120

    def test_build_filename_shape(self):
        name = build_filename("My Cool Video!", "abc123", "mp4")
        assert name.endswith(".mp4")
        assert "[abc123]" in name
        assert "/" not in name

    def test_content_disposition_header(self):
        cd = content_disposition("Video [id].mp4")
        assert cd.startswith("attachment;")
        assert "filename*=UTF-8''" in cd


# ---------------------------------------------------------------------------
# API contract: error schema + health/platforms (offline)
# ---------------------------------------------------------------------------
class TestApiContract:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "ok"
        assert "yt_dlp_version" in d
        assert isinstance(d["ffmpeg_available"], bool)

    def test_platforms(self, client):
        r = client.get("/api/platforms")
        assert r.status_code == 200
        plats = r.json()["platforms"]
        keys = {p["key"] for p in plats}
        assert keys == {"instagram"}
        # every entry has a status
        assert all(p["status"] in ("enabled", "coming_soon") for p in plats)

    def test_info_invalid_url_schema(self, client):
        r = client.post("/api/info", json={"url": "not-a-url"})
        assert r.status_code == 400
        err = r.json()["error"]
        assert err["code"] == ErrorCode.INVALID_URL
        assert "message" in err

    def test_info_ssrf_blocked(self, client):
        r = client.post("/api/info", json={"url": "http://169.254.169.254/"})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == ErrorCode.INVALID_URL

    def test_download_bad_kind(self, client):
        r = client.get("/api/download?url=https://www.instagram.com/reel/ABC/&format_id=v:1&kind=bogus")
        assert r.status_code == 400
        assert r.json()["error"]["code"] == ErrorCode.INVALID_URL

    def test_thumb_bad_type(self, client):
        r = client.get("/api/thumb?url=https://www.instagram.com/reel/ABC/&type=bmp")
        assert r.status_code == 400
        assert r.json()["error"]["code"] == ErrorCode.INVALID_URL
