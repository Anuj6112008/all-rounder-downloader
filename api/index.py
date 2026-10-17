"""Vercel entrypoint for IGDesk Downloader.

Vercel's Python runtime imports this module and exposes `app` (ASGI).
All /api/* routes are handled by the FastAPI app in backend/app.py.
"""
from backend.app import app  # noqa: F401

__all__ = ["app"]
