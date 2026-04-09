"""Request-scoped context via contextvars.

Provides a per-request UUID (``request_id``) that is:
- set by the ``RequestIDMiddleware`` at the start of each HTTP request
- available anywhere via ``get_request_id()``
- echoed in the ``X-Request-ID`` response header
- included in error envelopes and audit events
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Return the current request ID, or ``None`` outside a request."""
    return _request_id_var.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to every inbound HTTP request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Accept client-supplied ID if present, otherwise generate one.
        incoming = request.headers.get("X-Request-ID")
        rid = incoming if incoming else str(uuid.uuid4())
        token = _request_id_var.set(rid)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            _request_id_var.reset(token)
