"""Tests for the four daily-score direct tools.

Each test mocks the Oura endpoint and verifies:
- The right URL + params are called.
- The raw response is returned unmodified.
- The error envelope triggers on a non-200.
"""

from __future__ import annotations

import httpx
import respx

from oura_ring_mcp.server import mcp
from oura_ring_mcp.client import BASE_URL

# Resolve the tool callables from the FastMCP registry.
_tools = {t.name: t for t in mcp._tool_manager.list_tools()}


async def _call(name: str, **kwargs):
    """Call a registered MCP tool by name, injecting a fake PAT."""
    kwargs.setdefault("pat", "test-token")
    return await _tools[name].fn(**kwargs)


# ------------------------------------------------------------------
# oura_daily_sleep
# ------------------------------------------------------------------

@respx.mock
async def test_daily_sleep_single_date():
    payload = {"data": [{"day": "2026-04-28", "score": 82}], "next_token": None}
    respx.get(f"{BASE_URL}/daily_sleep", params={"start_date": "2026-04-28", "end_date": "2026-04-28"}).mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _call("oura_daily_sleep", date="2026-04-28")
    assert result == payload


@respx.mock
async def test_daily_sleep_range():
    payload = {"data": [{"day": "2026-04-27", "score": 75}, {"day": "2026-04-28", "score": 82}]}
    respx.get(f"{BASE_URL}/daily_sleep", params={"start_date": "2026-04-27", "end_date": "2026-04-28"}).mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _call("oura_daily_sleep", start_date="2026-04-27", end_date="2026-04-28")
    assert result["data"][1]["score"] == 82


@respx.mock
async def test_daily_sleep_error_envelope():
    respx.get(f"{BASE_URL}/daily_sleep").mock(return_value=httpx.Response(401, text="Unauthorized"))
    result = await _call("oura_daily_sleep", date="2026-04-28")
    assert result["error"] == "oura_api_error"
    assert result["status"] == 401


# ------------------------------------------------------------------
# oura_daily_readiness
# ------------------------------------------------------------------

@respx.mock
async def test_daily_readiness_single_date():
    payload = {"data": [{"day": "2026-04-28", "score": 79, "temperature_deviation": 0.12}]}
    respx.get(f"{BASE_URL}/daily_readiness", params={"start_date": "2026-04-28", "end_date": "2026-04-28"}).mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _call("oura_daily_readiness", date="2026-04-28")
    assert result["data"][0]["temperature_deviation"] == 0.12


@respx.mock
async def test_daily_readiness_error_envelope():
    respx.get(f"{BASE_URL}/daily_readiness").mock(return_value=httpx.Response(403, text="Forbidden"))
    result = await _call("oura_daily_readiness", date="2026-04-28")
    assert result["error"] == "oura_api_error"
    assert result["status"] == 403


# ------------------------------------------------------------------
# oura_daily_activity
# ------------------------------------------------------------------

@respx.mock
async def test_daily_activity_single_date():
    payload = {"data": [{"day": "2026-04-28", "steps": 8431, "active_calories": 512}]}
    respx.get(f"{BASE_URL}/daily_activity", params={"start_date": "2026-04-28", "end_date": "2026-04-28"}).mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _call("oura_daily_activity", date="2026-04-28")
    assert result["data"][0]["steps"] == 8431


@respx.mock
async def test_daily_activity_error_envelope():
    respx.get(f"{BASE_URL}/daily_activity").mock(return_value=httpx.Response(500, text="Server Error"))
    result = await _call("oura_daily_activity", date="2026-04-28")
    assert result["error"] == "oura_api_error"
    assert result["status"] == 500


# ------------------------------------------------------------------
# oura_daily_spo2
# ------------------------------------------------------------------

@respx.mock
async def test_daily_spo2_single_date():
    payload = {"data": [{"day": "2026-04-28", "spo2_percentage": {"average": 97.4}}]}
    respx.get(f"{BASE_URL}/daily_spo2", params={"start_date": "2026-04-28", "end_date": "2026-04-28"}).mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _call("oura_daily_spo2", date="2026-04-28")
    assert result["data"][0]["spo2_percentage"]["average"] == 97.4


@respx.mock
async def test_daily_spo2_empty_ok():
    """Empty data array is valid — Gen 2 devices may not have SpO2."""
    payload = {"data": []}
    respx.get(f"{BASE_URL}/daily_spo2", params={"start_date": "2026-04-28", "end_date": "2026-04-28"}).mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _call("oura_daily_spo2", date="2026-04-28")
    assert result["data"] == []
