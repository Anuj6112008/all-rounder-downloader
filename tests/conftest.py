"""Shared pytest fixtures for IGDesk Downloader tests."""
from __future__ import annotations

import os
import sys

import pytest

# Make the project root importable when running `pytest` from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    """A TestClient bound to the FastAPI app (no network needed)."""
    return TestClient(app)
