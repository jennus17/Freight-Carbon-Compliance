"""
Request middleware — correlation ID, structured access logging, HTTP metrics.

Runs once per request. Order of concerns inside ``dispatch``:
  1. Generate / accept ``X-Request-ID`` and stash on ``request.state``.
  2. Time the downstream handler.
  3. On the way out: attach the request id to the response, emit a single
     access-log line, record the HTTP histogram + counter.

The metrics path label uses the matched FastAPI route template (e.g.
``/api/v1/emissions/calculate``) rather than the raw path, so future
parameterised paths cannot blow up cardinality.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    status_class,
)


_log = logging.getLogger("app.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = (
            request.headers.get(settings.request_id_header)
            or uuid.uuid4().hex
        )
        request.state.request_id = request_id

        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - start
            _log.exception(
                "request failed",
                extra=_log_extra(request, request_id, status=500, duration_s=duration),
            )
            if settings.metrics_enabled:
                _record_metrics(request, status_code=500, duration_s=duration)
            raise

        duration = time.perf_counter() - start
        response.headers[settings.request_id_header] = request_id

        if settings.metrics_enabled:
            _record_metrics(request, status_code=response.status_code, duration_s=duration)

        _log.info(
            "request",
            extra=_log_extra(request, request_id, status=response.status_code, duration_s=duration),
        )
        return response


def _route_template(request: Request) -> str:
    """Pick the templated route path when available, else fall back to raw path."""
    route = request.scope.get("route")
    if route is not None and hasattr(route, "path"):
        return route.path
    return request.url.path


def _log_extra(request: Request, request_id: str, *, status: int, duration_s: float) -> dict:
    return {
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status": status,
        "duration_ms": round(duration_s * 1000, 2),
        "rapidapi_user": request.headers.get("X-RapidAPI-User"),
        "rapidapi_subscription": request.headers.get("X-RapidAPI-Subscription"),
        "user_agent": request.headers.get("User-Agent"),
    }


def _record_metrics(request: Request, *, status_code: int, duration_s: float) -> None:
    path = _route_template(request)
    if path == "/metrics":
        return  # never self-instrument the scrape endpoint
    HTTP_REQUESTS_TOTAL.labels(
        method=request.method,
        path=path,
        status_class=status_class(status_code),
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=request.method, path=path).observe(duration_s)
