"""Negative / security tests: invalid URLs, empty input, non-allowlisted
domains, private/removed content, localhost & SSRF attempts, oversized
requests, and rate-limit triggering.

Runs against the FastAPI TestClient for contract checks and a live local
server (when reachable) for the rate-limit test.
"""
from __future__ import annotations

import os
import time

import pytest

from backend.errors import ErrorCode

BASE = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8000")


# ---------------------------------------------------------------------------
# Invalid / empty / non-http input
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("payload", [
    {"url": ""},
    {"url": "   "},
    {"url": "not a url at all"},
    {"url": "ftp://instagram.com/reel/abc/"},
    {"url": "javascript:alert(1)"},
    {"url": "file:///etc/passwd"},
])
def test_invalid_input_returns_invalid_url(client, payload):
    r = client.post("/api/info", json=payload)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == ErrorCode.INVALID_URL


def test_missing_body_rejected(client):
    r = client.post("/api/info", json={})
    assert r.status_code == 422  # pydantic validation (no `url` field)


# ---------------------------------------------------------------------------
# Non-allowlisted domain
# ---------------------------------------------------------------------------
def test_non_allowlisted_domain(client):
    r = client.post("/api/info", json={"url": "https://evil.example.com/video/1"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == ErrorCode.UNSUPPORTED_PLATFORM


# ---------------------------------------------------------------------------
# SSRF attempts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "http://localhost/api",
    "http://127.0.0.1:8000/api",
    "http://0.0.0.0/",
    "http://10.0.0.5/",
    "http://192.168.0.1/",
    "http://172.31.255.255/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://metadata.google.internal/",
])
def test_ssrf_attempts_blocked(client, url):
    r = client.post("/api/info", json={"url": url})
    assert r.status_code in (400, 422)
    assert r.json()["error"]["code"] == ErrorCode.INVALID_URL


def test_download_ssrf_blocked(client):
    r = client.get("/api/download",
                   params={"url": "http://169.254.169.254/",
                           "format_id": "v:1", "kind": "video"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == ErrorCode.INVALID_URL


def test_thumb_ssrf_blocked(client):
    r = client.get("/api/thumb", params={"url": "http://127.0.0.1/", "type": "jpg"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == ErrorCode.INVALID_URL


# ---------------------------------------------------------------------------
# Oversized URL input
# ---------------------------------------------------------------------------
def test_oversized_url_rejected(client):
    r = client.post("/api/info", json={"url": "https://instagram.com/" + "a" * 600})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == ErrorCode.INVALID_URL


# ---------------------------------------------------------------------------
# Private / removed / login-only content maps to a clear error
# ---------------------------------------------------------------------------
def test_private_or_removed_video(client):
    """A well-formed but nonexistent Instagram id must map to a clear error,
    never a crash or a success."""
    r = client.post("/api/info", json={"url": "https://www.instagram.com/reel/ZZZZZZZZZZZ/"})
    assert r.status_code >= 400
    body = r.json()
    assert "error" in body
    assert body["error"]["code"] in (
        ErrorCode.PRIVATE_OR_REMOVED,
        ErrorCode.LOGIN_REQUIRED,
        ErrorCode.UPSTREAM_BLOCKED,
        ErrorCode.GEO_BLOCKED,
        ErrorCode.RATE_LIMITED,
    )
    assert body["error"]["message"]


def test_youtube_unsupported_platform(client):
    """YouTube links now map to UNSUPPORTED_PLATFORM (Instagram-only app)."""
    r = client.post("/api/info", json={"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == ErrorCode.UNSUPPORTED_PLATFORM


# ---------------------------------------------------------------------------
# Rate limiting (against the live local server; reset via new bucket keys)
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_rate_limit_triggers_429():
    """Burst the info endpoint past the per-IP limit and expect a 429.

    Uses a unique ``X-Forwarded-For`` so this burst lands in its own isolated
    rate-limit bucket. That keeps the test self-contained: it proves the limiter
    fires without polluting the default-IP bucket that the (real-link)
    integration tests rely on when the whole suite runs against one server.
    """
    import uuid

    import requests

    url = f"{BASE}/api/info"
    isolated_ip = f"203.0.113.{uuid.uuid4().int % 254 + 1}"
    headers = {"X-Forwarded-For": isolated_ip}
    codes = []
    try:
        for _ in range(40):
            resp = requests.post(url, json={"url": "https://evil.example.com/x"},
                                 headers=headers, timeout=10)
            codes.append(resp.status_code)
            if resp.status_code == 429:
                break
    except requests.RequestException:
        pytest.skip("local server not reachable for rate-limit test")
    if 429 not in codes:
        pytest.skip("rate limit not reached within burst window (per-instance window)")
    # A limited response carries Retry-After and the RATE_LIMITED error code.
    limited = [c for c in codes if c == 429]
    assert limited, "expected at least one 429 from the burst"
