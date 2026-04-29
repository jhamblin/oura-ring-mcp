"""Decorator that wraps tool handlers with structured error envelopes.

Tools should never raise — agents need a parseable response. This decorator catches
the project's known error types and returns them as `{"error": ..., "message": ...}`.
Unknown exceptions are re-raised so they surface in logs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec

from .auth import PATNotConfigured
from .client import OuraAPIError

P = ParamSpec("P")


def safe_tool(
    fn: Callable[P, Awaitable[dict[str, Any]]],
) -> Callable[P, Awaitable[dict[str, Any]]]:
    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> dict[str, Any]:
        try:
            return await fn(*args, **kwargs)
        except PATNotConfigured as e:
            return {"error": "pat_not_configured", "message": str(e)}
        except OuraAPIError as e:
            return {
                "error": "oura_api_error",
                "status": e.status,
                "endpoint": e.endpoint,
                "message": e.body[:500],
            }

    return wrapper
