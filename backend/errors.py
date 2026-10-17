"""Canonical error codes and the application-wide exception type.

Every API failure is expressed as :class:`AppError` and rendered to the client
as ``{"error": {"code": ..., "message": ...}}``.  Error codes are stable
strings so the frontend (and tests) can key off them.
"""
from __future__ import annotations

from typing import Any, Dict


class ErrorCode:
    """Stable, machine-readable error codes exposed by the API."""

    INVALID_URL = "INVALID_URL"
    UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"
    PRIVATE_OR_REMOVED = "PRIVATE_OR_REMOVED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    GEO_BLOCKED = "GEO_BLOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    TOO_LARGE = "TOO_LARGE"
    UPSTREAM_BLOCKED = "UPSTREAM_BLOCKED"
    INTERNAL = "INTERNAL"


#: Default HTTP status for each error code.
STATUS_BY_CODE: Dict[str, int] = {
    ErrorCode.INVALID_URL: 400,
    ErrorCode.UNSUPPORTED_PLATFORM: 400,
    ErrorCode.PRIVATE_OR_REMOVED: 404,
    ErrorCode.LOGIN_REQUIRED: 401,
    ErrorCode.GEO_BLOCKED: 451,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.TOO_LARGE: 413,
    ErrorCode.UPSTREAM_BLOCKED: 502,
    ErrorCode.INTERNAL: 500,
}


class AppError(Exception):
    """A user-safe application error carrying a stable code.

    Attributes:
        code: One of :class:`ErrorCode`'s members.
        message: Human-readable, user-safe message (never contains secrets
            or full upstream URLs).
        status: HTTP status code used when rendering the error.
    """

    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or STATUS_BY_CODE.get(code, 500)

    def to_payload(self) -> Dict[str, Any]:
        """Return the JSON body sent to clients."""
        return {"error": {"code": self.code, "message": self.message}}
