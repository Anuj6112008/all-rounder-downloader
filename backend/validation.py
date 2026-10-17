"""URL validation, normalisation and SSRF protection.

Every user-supplied URL goes through :func:`validate_and_detect` before any
network call.  The rules are deliberately strict:

* ``http``/``https`` schemes only (a missing scheme is assumed to be https)
* maximum length (500 chars by default)
* no embedded credentials (``user:pass@host``)
* no localhost / private / link-local / reserved IP literals
* host must belong to a registered platform (domain allowlist)
"""
from __future__ import annotations

import ipaddress
import re
from typing import Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from .config import settings
from .errors import AppError, ErrorCode
from .platforms import Platform, detect_platform

# Hostnames that must never be fetched, even if they resolve.
_BLOCKED_HOSTS = {
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata.google.internal", "instance-data",
}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa", ".localdomain")

_SCHEMELESS_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.\-]*\.[a-zA-Z]{2,}(/|$)")


def _is_blocked_ip(host: str) -> bool:
    """True if *host* is an IP literal in a non-public range."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # not an IP literal
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _host_blocked(host: str) -> bool:
    """True for localhost / internal / metadata hostnames."""
    if host in _BLOCKED_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in _BLOCKED_SUFFIXES)


def normalize_url(raw: str) -> Tuple[str, str]:
    """Normalise *raw* and return ``(normalized_url, host)``.

    Raises:
        AppError: INVALID_URL for anything malformed, too long, on a blocked
            host, or using a non-http(s) scheme.
    """
    if raw is None:
        raise AppError(ErrorCode.INVALID_URL, "URL is required.")
    url = raw.strip()
    if not url:
        raise AppError(ErrorCode.INVALID_URL, "URL is required.")
    if len(url) > settings.max_url_length:
        raise AppError(ErrorCode.INVALID_URL, f"URL is too long (max {settings.max_url_length} characters).")

    # Assume https when the user pastes a bare domain (e.g. "youtube.com/watch?...")
    # If a scheme is explicitly present, urlsplit() below will validate it.
    if "://" not in url:
        if _SCHEMELESS_RE.match(url):
            url = "https://" + url
        else:
            raise AppError(ErrorCode.INVALID_URL, "Only http(s) URLs are supported.")

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise AppError(ErrorCode.INVALID_URL, "Only http(s) URLs are supported.")
    if parts.username or parts.password:
        raise AppError(ErrorCode.INVALID_URL, "URLs with embedded credentials are not allowed.")

    host = (parts.hostname or "").lower().strip(".")
    if not host:
        raise AppError(ErrorCode.INVALID_URL, "Could not read the hostname from the URL.")
    if _host_blocked(host):
        raise AppError(ErrorCode.INVALID_URL, "This host is not allowed.")
    if _is_blocked_ip(host):
        raise AppError(ErrorCode.INVALID_URL, "This address is not allowed.")

    # Rebuild a clean URL: lowercase host, drop fragment, default port removed.
    netloc = host
    if parts.port and parts.port not in (80, 443):
        netloc = f"{host}:{parts.port}"
    normalized = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    return normalized, host


def validate_and_detect(raw: str, *, require_enabled: bool = True) -> Tuple[str, Platform]:
    """Validate *raw*, normalise it and resolve its platform.

    Args:
        raw: User-supplied URL.
        require_enabled: When True (default) a registered-but-disabled
            platform raises UNSUPPORTED_PLATFORM so the UI can show it as
            "coming soon" instead of failing confusingly later.

    Returns:
        ``(normalized_url, platform)``

    Raises:
        AppError: INVALID_URL or UNSUPPORTED_PLATFORM.
    """
    url, host = normalize_url(raw)
    platform = detect_platform(host)
    if platform is None:
        raise AppError(ErrorCode.UNSUPPORTED_PLATFORM, "This link is from a platform we don't support yet.")
    if require_enabled and not platform.enabled:
        raise AppError(
            ErrorCode.UNSUPPORTED_PLATFORM,
            f"{platform.name} support is coming soon.",
        )
    return url, platform


def validate_media_host(url: str) -> str:
    """SSRF guard for outbound media fetches (proxy / ffmpeg inputs).

    Ensures the URL is http(s), not an IP literal in a private range, not an
    internal hostname, and its host is on the media CDN allowlist.
    """
    from .platforms import is_media_host

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise AppError(ErrorCode.INTERNAL, "Refusing to fetch a non-http media URL.")
    host = (parts.hostname or "").lower().strip(".")
    if not host or _host_blocked(host) or _is_blocked_ip(host):
        raise AppError(ErrorCode.INTERNAL, "Refusing to fetch a blocked media host.")
    if not is_media_host(host):
        raise AppError(ErrorCode.INTERNAL, "Refusing to fetch a media host outside the allowlist.")
    return url
