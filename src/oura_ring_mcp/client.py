"""Async Oura v2 API client.

Responsibilities:
- Bearer-token GET requests against the Oura v2 usercollection base URL.
- `get_all()` for endpoints that paginate via `next_token` (sleep, heartrate, workout, session).
- Module-level redacting log filter on the `httpx` / `httpcore` loggers so a future
  `--debug` flag can never leak the PAT (mandatory per spec §4.1).
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

BASE_URL = "https://api.ouraring.com/v2/usercollection"
DEFAULT_TIMEOUT = 30.0

# Match either the full header line or just the bearer token, even if quoted/spaced oddly.
_REDACT_PATTERNS = (
    re.compile(r"Authorization['\"]?\s*[:=]\s*['\"]?Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+"),
)


class _RedactAuthHeader(logging.Filter):
    """Strip Authorization headers and bearer tokens from log records.

    Installed at module import so any logging downstream of httpx/httpcore is safe.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = msg
        for pat in _REDACT_PATTERNS:
            redacted = pat.sub("Authorization: [REDACTED]", redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


for _logger_name in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection"):
    logging.getLogger(_logger_name).addFilter(_RedactAuthHeader())


class OuraAPIError(RuntimeError):
    """Raised when Oura returns a non-2xx response."""

    def __init__(self, status: int, endpoint: str, body: str) -> None:
        self.status = status
        self.endpoint = endpoint
        self.body = body
        super().__init__(f"Oura API {endpoint} returned {status}: {body[:200]}")


class OuraClient:
    def __init__(
        self,
        pat: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {pat}"},
            timeout=timeout,
        )

    async def __aenter__(self) -> OuraClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, endpoint: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """Single GET. Returns the parsed JSON body. Raises OuraAPIError on non-200."""
        resp = await self._client.get(f"/{endpoint}", params=params or {})
        if resp.status_code != 200:
            raise OuraAPIError(resp.status_code, endpoint, resp.text)
        return resp.json()

    async def get_all(
        self, endpoint: str, params: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """Paginate through `next_token` and return the combined `data` list.

        Oura paginates `/sleep`, `/heartrate`, `/workout`, `/session`, and others.
        The `next_token` field in the response, when non-null, is passed back as a
        query parameter alongside the original params to fetch the next page.
        """
        items: list[dict[str, Any]] = []
        cursor: dict[str, str] = dict(params or {})
        while True:
            resp = await self.get(endpoint, cursor)
            items.extend(resp.get("data", []))
            next_token = resp.get("next_token")
            if not next_token:
                return items
            cursor["next_token"] = next_token
