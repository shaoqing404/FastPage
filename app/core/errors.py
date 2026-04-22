"""Unified error taxonomy and envelope for PageIndex service.

Provides stable machine-readable error codes, an AppError exception class,
and a helper to build the standard JSON error envelope.
"""

from __future__ import annotations


# ── Stable error codes ─────────────────────────────────────────────────────────

class ErrorCode:
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_TOKEN_INVALID = "AUTH_TOKEN_INVALID"
    AUTH_API_KEY_INVALID = "AUTH_API_KEY_INVALID"
    PROVIDER_URL_INVALID = "PROVIDER_URL_INVALID"
    PROVIDER_PROBE_FAILED = "PROVIDER_PROBE_FAILED"
    PROVIDER_MODEL_UNSUPPORTED = "PROVIDER_MODEL_UNSUPPORTED"
    UPLOAD_INVALID_FILE = "UPLOAD_INVALID_FILE"
    UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    CONFLICT_STATE = "CONFLICT_STATE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# ── HTTP status → error code fallback mapping ──────────────────────────────────

_STATUS_CODE_MAP: dict[int, str] = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.AUTH_TOKEN_INVALID,
    403: ErrorCode.AUTH_TOKEN_INVALID,
    404: ErrorCode.RESOURCE_NOT_FOUND,
    409: ErrorCode.CONFLICT_STATE,
    413: ErrorCode.UPLOAD_TOO_LARGE,
    422: ErrorCode.VALIDATION_ERROR,
    502: ErrorCode.PROVIDER_PROBE_FAILED,
}


def status_to_error_code(status_code: int) -> str:
    """Map an HTTP status code to the nearest stable error code."""
    return _STATUS_CODE_MAP.get(status_code, ErrorCode.INTERNAL_ERROR)


# ── AppError exception ─────────────────────────────────────────────────────────

class AppError(Exception):
    """Structured application error that maps to the standard error envelope.

    New code should raise ``AppError`` instead of bare ``HTTPException``
    whenever a stable error code applies.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict | list | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


# ── Envelope builder ───────────────────────────────────────────────────────────

def error_envelope(
    code: str,
    message: str,
    request_id: str | None = None,
    details: dict | list | None = None,
) -> dict:
    """Build the standard JSON error envelope."""
    body: dict = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }
    if details is not None:
        body["error"]["details"] = details
    return body
