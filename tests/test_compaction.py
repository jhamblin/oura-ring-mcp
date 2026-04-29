"""Tests for compact-mode field stripping (spec §6)."""

from __future__ import annotations

import copy

import httpx
import respx

from oura_mcp.client import BASE_URL
from oura_mcp.server import mcp
from oura_mcp.tools.compaction import (
    compact_sleep_session,
    compact_sleep_sessions,
    _summarize_items,
)

_tools = {t.name: t for t in mcp._tool_manager.list_tools()}


# ------------------------------------------------------------------
# Unit tests for _summarize_items
# ------------------------------------------------------------------


def test_summarize_hr_items():
    items = [{"bpm": 55, "timestamp": "..."}, {"bpm": 60, "timestamp": "..."}, {"bpm": 50, "timestamp": "..."}]
    s = _summarize_items(items)
    assert s == {"min": 50, "max": 60, "avg": 55.0, "samples": 3}


def test_summarize_hrv_items():
    items = [{"hrv": 30.0}, {"hrv": 40.0}, {"hrv": 50.0}]
    s = _summarize_items(items)
    assert s == {"min": 30.0, "max": 50.0, "avg": 40.0, "samples": 3}


def test_summarize_empty():
    s = _summarize_items([])
    assert s == {"min": None, "max": None, "avg": None, "samples": 0}


def test_summarize_items_with_none_values():
    items = [{"bpm": None}, {"bpm": 60}]
    s = _summarize_items(items)
    assert s["samples"] == 1
    assert s["avg"] == 60.0


def test_summarize_rounds_avg():
    items = [{"bpm": 55}, {"bpm": 56}, {"bpm": 57}]
    s = _summarize_items(items)
    assert s["avg"] == 56.0  # 168/3 = 56.0


# ------------------------------------------------------------------
# Unit tests for compact_sleep_session
# ------------------------------------------------------------------


FULL_SESSION = {
    "id": "test-session",
    "type": "long_sleep",
    "day": "2026-04-28",
    "deep_sleep_duration": 3600,
    "rem_sleep_duration": 5400,
    "light_sleep_duration": 14400,
    "awake_time": 1200,
    "efficiency": 91,
    "sleep_phase_5_min": "42221333222",
    "sleep_phase_30_sec": "4" * 200,
    "movement_30_sec": "1" * 200,
    "heart_rate": {
        "interval": 5,
        "items": [
            {"bpm": 52, "timestamp": "2026-04-28T00:00:00"},
            {"bpm": 55, "timestamp": "2026-04-28T00:05:00"},
            {"bpm": 48, "timestamp": "2026-04-28T00:10:00"},
        ],
        "timestamp": "2026-04-28T00:00:00",
    },
    "hrv": {
        "interval": 300,
        "items": [
            {"hrv": 35.0, "timestamp": "2026-04-28T00:00:00"},
            {"hrv": 45.0, "timestamp": "2026-04-28T00:05:00"},
        ],
        "timestamp": "2026-04-28T00:00:00",
    },
}


def test_compact_drops_bulky_strings():
    result = compact_sleep_session(FULL_SESSION)
    assert "sleep_phase_30_sec" not in result
    assert "movement_30_sec" not in result


def test_compact_keeps_sleep_phase_5_min():
    result = compact_sleep_session(FULL_SESSION)
    assert result["sleep_phase_5_min"] == "42221333222"


def test_compact_replaces_hr_items_with_summary():
    result = compact_sleep_session(FULL_SESSION)
    assert "items" not in result["heart_rate"]
    assert result["heart_rate"]["summary"] == {
        "min": 48,
        "max": 55,
        "avg": 51.67,
        "samples": 3,
    }
    # Non-items fields preserved
    assert result["heart_rate"]["interval"] == 5


def test_compact_replaces_hrv_items_with_summary():
    result = compact_sleep_session(FULL_SESSION)
    assert "items" not in result["hrv"]
    assert result["hrv"]["summary"] == {
        "min": 35.0,
        "max": 45.0,
        "avg": 40.0,
        "samples": 2,
    }


def test_compact_preserves_scalar_fields():
    result = compact_sleep_session(FULL_SESSION)
    assert result["deep_sleep_duration"] == 3600
    assert result["efficiency"] == 91
    assert result["id"] == "test-session"


def test_compact_does_not_mutate_original():
    original = copy.deepcopy(FULL_SESSION)
    compact_sleep_session(FULL_SESSION)
    assert FULL_SESSION == original


def test_compact_handles_session_without_timeseries():
    """Naps and short sessions may lack heart_rate/hrv/movement fields."""
    minimal = {"id": "nap", "type": "rest", "day": "2026-04-28", "efficiency": 80}
    result = compact_sleep_session(minimal)
    assert result["efficiency"] == 80
    assert "heart_rate" not in result


def test_compact_sessions_list():
    sessions = [FULL_SESSION, {"id": "nap", "type": "rest", "day": "2026-04-28"}]
    results = compact_sleep_sessions(sessions)
    assert len(results) == 2
    assert "sleep_phase_30_sec" not in results[0]
    assert results[1]["id"] == "nap"


# ------------------------------------------------------------------
# Integration: oura_sleep with format param
# ------------------------------------------------------------------


FIXTURE_WITH_TIMESERIES = {
    "data": [
        {
            **FULL_SESSION,
            "bedtime_start": "2026-04-27T23:30:00-07:00",
            "bedtime_end": "2026-04-28T07:00:00-07:00",
        }
    ],
    "next_token": None,
}


@respx.mock
async def test_oura_sleep_defaults_to_compact():
    respx.get(f"{BASE_URL}/sleep").mock(
        return_value=httpx.Response(200, json=FIXTURE_WITH_TIMESERIES)
    )
    result = await _tools["oura_sleep"].fn(date="2026-04-28", pat="test-token")
    session = result["data"][0]
    assert "sleep_phase_30_sec" not in session
    assert "movement_30_sec" not in session
    assert "summary" in session["heart_rate"]
    assert "items" not in session["heart_rate"]


@respx.mock
async def test_oura_sleep_full_mode_preserves_items():
    respx.get(f"{BASE_URL}/sleep").mock(
        return_value=httpx.Response(200, json=FIXTURE_WITH_TIMESERIES)
    )
    result = await _tools["oura_sleep"].fn(date="2026-04-28", format="full", pat="test-token")
    session = result["data"][0]
    assert "sleep_phase_30_sec" in session
    assert "movement_30_sec" in session
    assert "items" in session["heart_rate"]
    assert "items" in session["hrv"]
