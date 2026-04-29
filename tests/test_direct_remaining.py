"""Tests for the remaining direct tools added in step 8."""

from __future__ import annotations

import httpx
import respx

from oura_mcp.client import BASE_URL
from oura_mcp.server import mcp

_tools = {t.name: t for t in mcp._tool_manager.list_tools()}


async def _call(name: str, **kwargs):
    kwargs.setdefault("pat", "test-token")
    return await _tools[name].fn(**kwargs)


# ---------------------------------------------------------------------------
# Daily Gen-3+ endpoints — one happy-path + one error-envelope per tool
# ---------------------------------------------------------------------------


@respx.mock
async def test_daily_stress():
    payload = {"data": [{"day": "2026-04-28", "stress_high": 3600, "recovery_high": 1800}]}
    respx.get(f"{BASE_URL}/daily_stress", params={"start_date": "2026-04-28", "end_date": "2026-04-28"}).mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _call("oura_daily_stress", date="2026-04-28")
    assert result["data"][0]["stress_high"] == 3600


@respx.mock
async def test_daily_stress_error_envelope():
    respx.get(f"{BASE_URL}/daily_stress").mock(return_value=httpx.Response(403, text="Forbidden"))
    result = await _call("oura_daily_stress", date="2026-04-28")
    assert result["error"] == "oura_api_error"
    assert result["status"] == 403


@respx.mock
async def test_daily_resilience():
    payload = {"data": [{"day": "2026-04-28", "level": "adequate"}]}
    respx.get(f"{BASE_URL}/daily_resilience", params={"start_date": "2026-04-28", "end_date": "2026-04-28"}).mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _call("oura_daily_resilience", date="2026-04-28")
    assert result["data"][0]["level"] == "adequate"


@respx.mock
async def test_daily_cardiovascular_age():
    payload = {"data": [{"day": "2026-04-28", "vascular_age": 38}]}
    respx.get(f"{BASE_URL}/daily_cardiovascular_age", params={"start_date": "2026-04-28", "end_date": "2026-04-28"}).mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _call("oura_daily_cardiovascular_age", date="2026-04-28")
    assert result["data"][0]["vascular_age"] == 38


@respx.mock
async def test_daily_sleep_time():
    payload = {"data": [{"day": "2026-04-28", "status": "recommended",
                          "optimal_bedtime": {"start_offset": -3600, "end_offset": -1800}}]}
    respx.get(f"{BASE_URL}/sleep_time", params={"start_date": "2026-04-28", "end_date": "2026-04-28"}).mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = await _call("oura_daily_sleep_time", date="2026-04-28")
    assert result["data"][0]["status"] == "recommended"


# ---------------------------------------------------------------------------
# Paginated activity/event endpoints
# ---------------------------------------------------------------------------


@respx.mock
async def test_workouts_returns_data():
    payload = {"data": [{"id": "w1", "activity": "running", "day": "2026-04-28"}], "next_token": None}
    respx.get(f"{BASE_URL}/workout").mock(return_value=httpx.Response(200, json=payload))
    result = await _call("oura_workouts", date="2026-04-28")
    assert result["data"][0]["activity"] == "running"


@respx.mock
async def test_workouts_paginated():
    route = respx.get(f"{BASE_URL}/workout")
    route.mock(side_effect=[
        httpx.Response(200, json={"data": [{"id": "w1"}], "next_token": "tok"}),
        httpx.Response(200, json={"data": [{"id": "w2"}], "next_token": None}),
    ])
    result = await _call("oura_workouts", date="2026-04-28")
    assert len(result["data"]) == 2


@respx.mock
async def test_sessions_returns_data():
    payload = {"data": [{"id": "s1", "type": "meditation", "day": "2026-04-28"}], "next_token": None}
    respx.get(f"{BASE_URL}/session").mock(return_value=httpx.Response(200, json=payload))
    result = await _call("oura_sessions", date="2026-04-28")
    assert result["data"][0]["type"] == "meditation"


@respx.mock
async def test_rest_mode_period():
    payload = {"data": [{"id": "r1", "start_day": "2026-04-25", "end_day": "2026-04-27"}], "next_token": None}
    respx.get(f"{BASE_URL}/rest_mode_period").mock(return_value=httpx.Response(200, json=payload))
    result = await _call("oura_rest_mode_period", start_date="2026-04-25", end_date="2026-04-28")
    assert result["data"][0]["start_day"] == "2026-04-25"


# ---------------------------------------------------------------------------
# oura_tags — enhanced_tag preferred, fallback to tag on 404
# ---------------------------------------------------------------------------


@respx.mock
async def test_tags_uses_enhanced_tag():
    payload = {"data": [{"id": "t1", "tag_type_code": "tag_custom", "text": "good night"}], "next_token": None}
    respx.get(f"{BASE_URL}/enhanced_tag").mock(return_value=httpx.Response(200, json=payload))
    result = await _call("oura_tags", date="2026-04-28")
    assert result["_source"] == "enhanced_tag"
    assert result["data"][0]["text"] == "good night"


@respx.mock
async def test_tags_falls_back_on_404():
    respx.get(f"{BASE_URL}/enhanced_tag").mock(return_value=httpx.Response(404, text="Not Found"))
    respx.get(f"{BASE_URL}/tag").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "t2", "text": "old tag"}], "next_token": None})
    )
    result = await _call("oura_tags", date="2026-04-28")
    assert result["_source"] == "tag"
    assert result["data"][0]["text"] == "old tag"


@respx.mock
async def test_tags_non_404_error_returned_as_envelope():
    respx.get(f"{BASE_URL}/enhanced_tag").mock(return_value=httpx.Response(500, text="Server Error"))
    result = await _call("oura_tags", date="2026-04-28")
    assert result["error"] == "oura_api_error"
    assert result["status"] == 500


# ---------------------------------------------------------------------------
# oura_heart_rate — compact vs full, default datetime params
# ---------------------------------------------------------------------------


@respx.mock
async def test_heart_rate_compact_default():
    items = [{"timestamp": "2026-04-28T00:00:00", "bpm": 52},
             {"timestamp": "2026-04-28T00:00:05", "bpm": 60},
             {"timestamp": "2026-04-28T00:00:10", "bpm": 50}]
    respx.get(f"{BASE_URL}/heartrate").mock(
        return_value=httpx.Response(200, json={"data": items, "next_token": None})
    )
    result = await _call("oura_heart_rate")
    assert "summary" in result
    assert result["summary"]["min"] == 50
    assert result["summary"]["max"] == 60
    assert result["summary"]["samples"] == 3
    assert "data" not in result


@respx.mock
async def test_heart_rate_full_mode():
    items = [{"timestamp": "2026-04-28T00:00:00", "bpm": 55}]
    respx.get(f"{BASE_URL}/heartrate").mock(
        return_value=httpx.Response(200, json={"data": items, "next_token": None})
    )
    result = await _call("oura_heart_rate", format="full")
    assert "data" in result
    assert result["data"][0]["bpm"] == 55
    assert "summary" not in result


@respx.mock
async def test_heart_rate_explicit_datetime():
    respx.get(f"{BASE_URL}/heartrate",
              params={"start_datetime": "2026-04-28T00:00:00-07:00",
                      "end_datetime": "2026-04-28T07:00:00-07:00"}).mock(
        return_value=httpx.Response(200, json={"data": [], "next_token": None})
    )
    result = await _call(
        "oura_heart_rate",
        start_datetime="2026-04-28T00:00:00-07:00",
        end_datetime="2026-04-28T07:00:00-07:00",
    )
    assert result["summary"]["samples"] == 0


@respx.mock
async def test_heart_rate_error_envelope():
    respx.get(f"{BASE_URL}/heartrate").mock(return_value=httpx.Response(401, text="Unauthorized"))
    result = await _call("oura_heart_rate")
    assert result["error"] == "oura_api_error"


# ---------------------------------------------------------------------------
# oura_ring_configuration
# ---------------------------------------------------------------------------


@respx.mock
async def test_ring_configuration():
    payload = {"data": [{"id": "ring1", "color": "brushed_silver", "hardware_type": "gen3"}]}
    respx.get(f"{BASE_URL}/ring_configuration").mock(return_value=httpx.Response(200, json=payload))
    result = await _call("oura_ring_configuration")
    assert result["data"][0]["hardware_type"] == "gen3"
