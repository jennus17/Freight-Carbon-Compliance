"""
RapidAPI gateway authentication.

When the API is published on RapidAPI, every request first hits the
RapidAPI proxy, which authenticates the consumer (using their personal
``X-RapidAPI-Key``) and then forwards the call to our origin with an
extra header — ``X-RapidAPI-Proxy-Secret`` — that only the proxy and we
know. Validating this header is what stops people from discovering the
origin URL and bypassing RapidAPI (and the billing) altogether.

Behaviour
---------
* If ``settings.rapidapi_proxy_secret`` is empty → check is disabled
  (this is the dev / local default — tests do not need to inject the header).
* Otherwise → request must carry a header whose value matches that secret,
  else **401 Unauthorized**.
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.core.config import settings


_HEADER_NAME = "X-RapidAPI-Proxy-Secret"


async def verify_rapidapi_proxy(
    x_rapidapi_proxy_secret: str | None = Header(
        default=None,
        alias=_HEADER_NAME,
        description=(
            "Shared secret injected by the RapidAPI gateway. Required in "
            "production deployments; ignored when the origin runs in dev mode."
        ),
        include_in_schema=False,
    ),
) -> None:
    expected = settings.rapidapi_proxy_secret
    if not expected:
        return

    if not x_rapidapi_proxy_secret or not hmac.compare_digest(
        x_rapidapi_proxy_secret, expected
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Invalid or missing X-RapidAPI-Proxy-Secret header. Direct "
                "requests to the origin are not permitted; please route via "
                "the RapidAPI gateway."
            ),
            headers={"WWW-Authenticate": "RapidAPI-Proxy"},
        )
