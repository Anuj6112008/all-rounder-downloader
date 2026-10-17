"""Platform adapter registry.

Adding a platform is a single :class:`Platform` entry.  The registry drives
three things:

* URL validation / domain allowlist (``domains``)
* Frontend icon + label (``icon``, ``name``)
* The "enabled" vs "coming soon" state shown in the UI (``enabled``)

``MEDIA_CDN_DOMAINS`` lists the CDN hosts that media bytes are allowed to be
fetched from / proxied to.  This is a separate, tighter allowlist than the
page-domain allowlist and is what defends the proxy against SSRF.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Platform:
    """A single supported (or planned) platform."""

    key: str
    name: str
    icon: str                 # short emoji used in the UI badge
    domains: Tuple[str, ...]  # registrable domains that identify this platform
    enabled: bool = True      # switch False to show it as "coming soon"
    note: str = ""            # shown in the UI / docs when not enabled


#: Order matters only for display.  `enabled=True` means the platform has
#: passed the live integration tests and the UI offers it as working.
PLATFORMS: Tuple[Platform, ...] = (
    Platform(
        key="youtube",
        name="YouTube",
        icon="▶️",
        domains=("youtube.com", "youtu.be", "m.youtube.com", "www.youtube.com",
                 "youtube-nocookie.com", "music.youtube.com"),
        enabled=True,
    ),
    Platform(
        key="instagram",
        name="Instagram",
        icon="📸",
        domains=("instagram.com", "instagr.am", "www.instagram.com", "ddinstagram.com"),
        enabled=True,
    ),
    # ---- Candidates: enabled only after they pass live tests --------------
    Platform(
        key="facebook",
        name="Facebook",
        icon="👍",
        domains=("facebook.com", "fb.watch", "fb.com", "www.facebook.com", "m.facebook.com"),
        enabled=False,
        note="Public Facebook videos - coming soon",
    ),
    Platform(
        key="x",
        name="X (Twitter)",
        icon="🐦",
        domains=("x.com", "twitter.com", "mobile.twitter.com", "www.x.com", "www.twitter.com",
                 "twimg.com"),
        enabled=False,
        note="Public posts - coming soon",
    ),
    Platform(
        key="tiktok",
        name="TikTok",
        icon="🎵",
        domains=("tiktok.com", "vm.tiktok.com", "www.tiktok.com", "m.tiktok.com"),
        enabled=False,
        note="Public videos - coming soon",
    ),
    Platform(
        key="pinterest",
        name="Pinterest",
        icon="📌",
        domains=("pinterest.com", "pin.it", "www.pinterest.com", "in.pinterest.com", "br.pinterest.com"),
        enabled=False,
        note="Public pins - coming soon",
    ),
    Platform(
        key="reddit",
        name="Reddit",
        icon="👽",
        domains=("reddit.com", "redd.it", "www.reddit.com", "v.redd.it", "old.reddit.com", "new.reddit.com"),
        enabled=False,
        note="Public posts - coming soon",
    ),
    Platform(
        key="vimeo",
        name="Vimeo",
        icon="🎬",
        domains=("vimeo.com", "player.vimeo.com", "www.vimeo.com"),
        enabled=False,
        note="Public videos - coming soon",
    ),
    Platform(
        key="soundcloud",
        name="SoundCloud",
        icon="☁️",
        domains=("soundcloud.com", "m.soundcloud.com", "www.soundcloud.com"),
        enabled=False,
        note="Public tracks - coming soon",
    ),
    Platform(
        key="dailymotion",
        name="Dailymotion",
        icon="🎥",
        domains=("dailymotion.com", "dai.ly", "www.dailymotion.com", "geo.dailymotion.com"),
        enabled=False,
        note="Public videos - coming soon",
    ),
)

_BY_DOMAIN: Dict[str, Platform] = {}
for _p in PLATFORMS:
    for _d in _p.domains:
        _BY_DOMAIN[_d.lower()] = _p


#: Hosts media bytes may be fetched from (page domains + known media CDNs).
#: Kept deliberately tight; anything not listed here is refused by the proxy.
MEDIA_CDN_DOMAINS: Tuple[str, ...] = (
    # YouTube
    "googlevideo.com", "ytimg.com", "youtube.com", "youtube-nocookie.com",
    # Instagram / Meta
    "fbcdn.net", "cdninstagram.com", "instagram.com",
    # Facebook
    "fbcdn.net", "facebook.com",
    # X / Twitter
    "twimg.com", "twitter.com", "x.com",
    # TikTok
    "tiktokcdn.com", "tiktokv.com", "tiktok.com", "tiktokcdn-us.com",
    # Pinterest
    "pinimg.com", "pinterest.com",
    # Reddit
    "redd.it", "v.redd.it", "redditmedia.com", "reddit.com",
    # Vimeo
    "vimeocdn.com", "vimeo.com",
    # SoundCloud
    "sndcdn.com", "scdn.co", "soundcloud.com",
    # Dailymotion
    "dailymotion.com", "static.dailymotion.com", "proxy.dailymotion.com",
)


def detect_platform(host: str) -> Optional[Platform]:
    """Return the :class:`Platform` for a hostname, or ``None``.

    Matching is exact-on-registrable-domain (``www.`` prefix tolerated).
    Sub-subdomains such as ``video.twimg.com`` are matched by suffix against
    the registrable domains in the registry.
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
            "note": p.note or (None if p.enabled else "Coming soon"),
        }
        for p in PLATFORMS
    ]
