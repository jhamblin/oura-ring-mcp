"""Tests for the safe_tool error envelope decorator."""

from __future__ import annotations

from oura_mcp._errors import safe_tool
from oura_mcp.auth import PATNotConfigured
from oura_mcp.client import OuraAPIError


async def test_safe_tool_catches_pat_not_configured():
    @safe_tool
    async def fn():
        raise PATNotConfigured("no pat")

    result = await fn()
    assert result["error"] == "pat_not_configured"
    assert "no pat" in result["message"]


async def test_safe_tool_catches_oura_api_error():
    @safe_tool
    async def fn():
        raise OuraAPIError(status=403, endpoint="/sleep", body="Forbidden")

    result = await fn()
    assert result["error"] == "oura_api_error"
    assert result["status"] == 403


async def test_safe_tool_catches_unexpected_exception():
    """A bare TypeError (e.g. 'in' against None) must return an error envelope, not raise."""
    @safe_tool
    async def fn():
        raise TypeError("argument of type 'NoneType' is not iterable")

    result = await fn()
    assert result["error"] == "internal_error"
    assert result["type"] == "TypeError"
    assert "NoneType" in result["message"]


async def test_safe_tool_passes_through_return_value():
    @safe_tool
    async def fn():
        return {"data": [1, 2, 3]}

    result = await fn()
    assert result == {"data": [1, 2, 3]}
