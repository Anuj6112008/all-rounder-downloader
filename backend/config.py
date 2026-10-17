"""Central configuration for IGDesk Downloader.

All tunables live here and are read from environment variables so that no
secret or environment-specific value is ever hardcoded.  See ``.env.example``
for the full list.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import List, Tuple

PROJECT_NAME = "IGDesk Downloader"
PROJECT_VERSION = "1.0.0"


def _int_env(name: str, default: int) -> int:
    """Read an int from the environment, falling back to *default*."""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    """Read a boolean-ish value from the environment."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings derived from the environment."""

    # ---- Limits -----------------------------------------------------------
    max_url_length: int = 500
    max_file_bytes: int = field(default_factory=lambda: _int_env("MAX_FILE_BYTES", 300 * 1024 * 1024))
    max_duration_seconds: int = field(default_factory=lambda: _int_env("MAX_DURATION_SECONDS", 1200))
    max_thumbnail_bytes: int = 20 * 1024 * 1024

    # ---- Network ----------------------------------------------------------
    socket_timeout: int = 20
    probe_timeout: float = 8.0
    upstream_connect_timeout: float = 15.0
    chunk_size: int = 64 * 1024
    job_budget_seconds: int = field(default_factory=lambda: _int_env("JOB_BUDGET_SECONDS", 240))

    # ---- Caching (best effort, in-memory, per warm instance) ---------------
    info_cache_ttl: int = field(default_factory=lambda: _int_env("INFO_CACHE_TTL", 120))

    # ---- Rate limiting (best effort on serverless) -------------------------
    rate_limit_info_per_min: int = field(default_factory=lambda: _int_env("RATE_LIMIT_INFO_PER_MIN", 30))
    rate_limit_download_per_min: int = field(default_factory=lambda: _int_env("RATE_LIMIT_DOWNLOAD_PER_MIN", 10))
    rate_limit_thumb_per_min: int = field(default_factory=lambda: _int_env("RATE_LIMIT_THUMB_PER_MIN", 20))

    # ---- Media pipeline -----------------------------------------------------
    allow_direct_redirect: bool = field(default_factory=lambda: _bool_env("ALLOW_DIRECT_REDIRECT", True))

    # ---- CORS ---------------------------------------------------------------
    allowed_origins: Tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip()
            for o in os.getenv(
                "ALLOWED_ORIGINS",
                "http://localhost:3000,http://localhost:5173,http://127.0.0.1:8000,http://localhost:8000",
            ).split(",")
            if o.strip()
        )
    )

    # ---- Temp dir (Vercel functions: only /tmp is writable) ------------------
    tmp_dir: str = field(default_factory=lambda: os.getenv("TMPDIR_OVERRIDE") or tempfile.gettempdir())


settings = Settings()


def allowed_origins_with(extra: List[str]) -> List[str]:
    """Return the configured CORS allowlist plus any extra dev origins."""
    return list(dict.fromkeys([*settings.allowed_origins, *extra]))
