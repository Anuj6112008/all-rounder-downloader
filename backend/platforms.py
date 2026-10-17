"""Platform adapter registry — Instagram-dedicated.

IGDesk Downloader supports one platform: **Instagram**.  The registry shape is
kept intentionally minimal (one :class:`Platform` entry) so the codebase stays
easy to reason about, while remaining extensible if a platform is ever added.

The registry drives:

* URL validation / domain allowlist (``domains``)
* Frontend icon + label (``icon``, ``name``)

``MEDIA_CDN_DOMAINS`` lists the CDN hosts that media bytes are allowed to be
fetched from / proxied to.  This is a separate, tighter allowlist than the
page-domain allowlist and is what defends the proxy against SSRF.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Platform:
    """A single supported platform."""

    key: str
    name: str
    icon: str                 # short emoji used in the UI badge
    domains: Tuple[str, ...]  # registrable domains that identify this platform
    enabled: bool = True      # kept for registry compatibility
    note: str = ""            # shown in the UI / docs when not enabled


#: One entry per platform.  IGDesk Downloader is Instagram-only by design.
PLATFORMS: List[Platform] = [
    Platform(
        key="instagram",
        name="Instagram",
        icon="📷",
        domains=("instagram.com", "instagr.am"),
        enabled=True,
    ),
]

#: domain (lowercased) -> platform, for exact + suffix host matching.
_BY_DOMAIN: Dict[str, Platform] = {}
for _p in PLATFORMS:
    for _d in _p.domains:
        _BY_DOMAIN[_d.lower()] = _p

#: CDN hosts media may be fetched from / proxied to (SSRF allowlist).
#: Kept tight — only the CDNs Instagram actually serves media from.
MEDIA_CDN_DOMAINS: Tuple[str, ...] = (
    "cdninstagram.com",
    "fbcdn.net",
)


def detect_platform(host: str) -> Optional[Platform]:
    """Return the :class:`Platform` for a hostname, or ``None``.

    Matching is exact-on-registrable-domain (``www.`` prefix tolerated).
    Sub-subdomains such as ``scontent.cdninstagram.com`` are matched by suffix
    against the registrable domains in the registry.
    """
    host = host.lower().strip(".")
    if host in _BY_DOMAIN:
        return _BY_DOMAIN[host]
    # Suffix match against registrable domains (e.g. cdn.example.com).
    for domain, platform in _BY_DOMAIN.items():
        bare = domain[4:] if domain.startswith("www.") else domain
        if host.endswith("." + bare):
            return platform
    return None


def is_media_host(host: str) -> bool:
    """True if *host* is on the media CDN allowlist (SSRF guard)."""
    host = host.lower().strip(".")
    for entry in MEDIA_CDN_DOMAINS:
        bare = entry[4:] if entry.startswith("www.") else entry
        if host == bare or host.endswith("." + bare):
            return True
    return False


def public_platform_list() -> List[dict]:
    """Serialise the registry for the ``/api/platforms`` endpoint."""
    return [
        {
            "key": p.key,
            "name": p.name,
            "icon": p.icon,
            "enabled": p.enabled,
            "status": "enabled" if p.enabled else "coming_soon",
            "note": p.note or ("Supported" if p.enabled else "Coming soon"),
        }
        for p in PLATFORMS
    ]
