"""Tests for derived tools: hypnogram, percentiles, rolling_average, summary_table."""

from __future__ import annotations

import httpx
import respx

from oura_mcp.client import BASE_URL
from oura_mcp.server import mcp
from oura_mcp.tools.derived import (
    _date_range,
    _percentile_nearest_rank,
    _primary_session,
    _render_hypnogram,
    _secs_to_min,
    HYPNO_KEY,
)

_tools = {t.name: t for t in mcp._tool_manager.list_tools()}


async def _call(name: str, **kwargs):
    kwargs.setdefault("pat", "test-token")
    return await _tools[name].fn(**kwargs)


# ---------------------------------------------------------------------------
# Unit: helper functions
# ---------------------------------------------------------------------------


def test_render_hypnogram_maps_chars():
    assert _render_hypnogram("1234") == "█░▒·"


def test_render_hypnogram_unknown_char():
    assert _render_hypnogram("19") == "█?"


def test_render_hypnogram_empty():
    assert _render_hypnogram("") == "—"


def test_render_hypnogram_chars_per_5min():
    assert _render_hypnogram("12", chars_per_5min=2) == "██░░"


def test_primary_session_prefers_long_sleep():
    sessions = [
        {"type": "rest", "total_sleep_duration": 9000},
        {"type": "long_sleep", "total_sleep_duration": 7200},
    ]
    assert _primary_session(sessions)["type"] == "long_sleep"


def test_primary_session_longest_long_sleep():
    sessions = [
        {"type": "long_sleep", "total_sleep_duration": 7200},
        {"type": "long_sleep", "total_sleep_duration": 9000},
    ]
    assert _primary_session(sessions)["total_sleep_duration"] == 9000


def test_primary_session_falls_back_to_longest():
    sessions = [
        {"type": "rest", "total_sleep_duration": 1800},
        {"type": "rest", "total_sleep_duration": 3600},
    ]
    assert _primary_session(sessions)["total_sleep_duration"] == 3600


def test_primary_session_empty():
    assert _primary_session([]) is None


def test_percentile_nearest_rank_median():
    # ceil(50/100 * 5) - 1 = ceil(2.5) - 1 = 3 - 1 = 2 → data[2] = 3.0
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _percentile_nearest_rank(data, 50) == 3.0


def test_percentile_nearest_rank_single():
    assert _percentile_nearest_rank([42.0], 95) == 42.0


def test_percentile_nearest_rank_p100():
    data = [1.0, 2.0, 3.0]
    assert _percentile_nearest_rank(data, 100) == 3.0


def test_date_range_single():
    assert _date_range("2026-04-28", "2026-04-28") == ["2026-04-28"]


def test_date_range_multi():
    result = _date_range("2026-04-26", "2026-04-28")
    assert result == ["2026-04-26", "2026-04-27", "2026-04-28"]


def test_secs_to_min():
    assert _secs_to_min(3660) == 61
    assert _secs_to_min(0) == 0
    assert _secs_to_min(None) is None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SLEEP_FIXTURE = {
    "data": [
        {
            "id": "s1",
            "type": "long_sleep",
            "day": "2026-04-27",
            "bedtime_start": "2026-04-26T23:45:00-07:00",
            "total_sleep_duration": 23400,
            "deep_sleep_duration": 3600,
            "rem_sleep_duration": 6000,
            "light_sleep_duration": 13800,
            "awake_time": 1200,
            "efficiency": 90,
            "average_hrv": 40,
            "lowest_heart_rate": 52,
            "sleep_phase_5_min": "42221333222",
        },
        {
            "id": "s2",
            "type": "long_sleep",
            "day": "2026-04-28",
            "bedtime_start": "2026-04-28T00:05:00-07:00",
            "total_sleep_duration": 25200,
            "deep_sleep_duration": 5400,
            "rem_sleep_duration": 7200,
            "light_sleep_duration": 12600,
            "awake_time": 900,
            "efficiency": 93,
            "average_hrv": 45,
            "lowest_heart_rate": 50,
            "sleep_phase_5_min": "42222133322",
        },
    ],
    "next_token": None,
}

DAILY_SLEEP_FIXTURE = {
    "data": [
        {"day": "2026-04-27", "score": 78},
        {"day": "2026-04-28", "score": 85},
    ]
}

DAILY_READINESS_FIXTURE = {
    "data": [
        {"day": "2026-04-27", "score": 72},
        {"day": "2026-04-28", "score": 81},
    ]
}


# ---------------------------------------------------------------------------
# oura_render_hypnogram
# ---------------------------------------------------------------------------


@respx.mock
async def test_render_hypnogram_tool():
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=SLEEP_FIXTURE))
    result = await _call("oura_render_hypnogram", date="2026-04-28")
    # "42222133322" → ·░░░░█▒▒▒░░
    assert result["hypnogram"] == "·░░░░█▒▒▒░░"
    assert result["key"] == HYPNO_KEY
    assert result["session_type"] == "long_sleep"
    assert result["total_minutes"] == 420


@respx.mock
async def test_render_hypnogram_no_data():
    respx.get(f"{BASE_URL}/sleep").mock(
        return_value=httpx.Response(200, json={"data": [], "next_token": None})
    )
    result = await _call("oura_render_hypnogram", date="2026-04-28")
    assert result["hypnogram"] is None
    assert result["error"] == "no_data"


# ---------------------------------------------------------------------------
# oura_percentiles
# ---------------------------------------------------------------------------


@respx.mock
async def test_percentiles_deep_sleep():
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=SLEEP_FIXTURE))
    result = await _call(
        "oura_percentiles",
        metric="deep_sleep_duration",
        start_date="2026-04-27",
        end_date="2026-04-28",
    )
    assert result["count"] == 2
    assert result["min"] == 3600.0
    assert result["max"] == 5400.0
    assert result["mean"] == 4500.0
    assert "50" in result["percentiles"]


@respx.mock
async def test_percentiles_custom_percentiles():
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=SLEEP_FIXTURE))
    result = await _call(
        "oura_percentiles",
        metric="efficiency",
        start_date="2026-04-27",
        end_date="2026-04-28",
        percentiles=[25, 75],
    )
    assert set(result["percentiles"].keys()) == {"25", "75"}


@respx.mock
async def test_percentiles_no_data():
    respx.get(f"{BASE_URL}/sleep").mock(
        return_value=httpx.Response(200, json={"data": [], "next_token": None})
    )
    result = await _call(
        "oura_percentiles",
        metric="deep_sleep_duration",
        start_date="2026-04-28",
        end_date="2026-04-28",
    )
    assert result["count"] == 0
    assert result["error"] == "no_data"


@respx.mock
async def test_percentiles_missing_metric_excluded():
    """Sessions without the requested metric field should be silently skipped."""
    fixture = {
        "data": [
            {"id": "s1", "type": "long_sleep", "day": "2026-04-28",
             "total_sleep_duration": 7200},  # no 'nonexistent_field'
        ],
        "next_token": None,
    }
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=fixture))
    result = await _call(
        "oura_percentiles",
        metric="nonexistent_field",
        start_date="2026-04-28",
        end_date="2026-04-28",
    )
    assert result["count"] == 0
    assert result["error"] == "no_data"


# ---------------------------------------------------------------------------
# oura_rolling_average
# ---------------------------------------------------------------------------


@respx.mock
async def test_rolling_average_basic():
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=SLEEP_FIXTURE))
    result = await _call(
        "oura_rolling_average",
        metric="deep_sleep_duration",
        start_date="2026-04-27",
        end_date="2026-04-28",
        window=7,
    )
    assert result["metric"] == "deep_sleep_duration"
    assert result["window"] == 7
    assert len(result["data"]) == 2

    row0 = result["data"][0]
    assert row0["date"] == "2026-04-27"
    assert row0["value"] == 3600.0
    assert row0["rolling_avg"] == 3600.0  # window of 1

    row1 = result["data"][1]
    assert row1["date"] == "2026-04-28"
    assert row1["value"] == 5400.0
    assert row1["rolling_avg"] == 4500.0  # (3600+5400)/2


@respx.mock
async def test_rolling_average_gap_days():
    """Days with no session should have value=None and be excluded from window."""
    fixture = {
        "data": [
            {"id": "s1", "type": "long_sleep", "day": "2026-04-26",
             "total_sleep_duration": 7200, "deep_sleep_duration": 3600},
            # Apr 27 missing
            {"id": "s2", "type": "long_sleep", "day": "2026-04-28",
             "total_sleep_duration": 7200, "deep_sleep_duration": 7200},
        ],
        "next_token": None,
    }
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=fixture))
    result = await _call(
        "oura_rolling_average",
        metric="deep_sleep_duration",
        start_date="2026-04-26",
        end_date="2026-04-28",
        window=3,
    )
    rows = {r["date"]: r for r in result["data"]}
    assert rows["2026-04-27"]["value"] is None
    # Rolling avg for Apr 28 should use only Apr 26 and Apr 28 (skip None)
    assert rows["2026-04-28"]["rolling_avg"] == 5400.0  # (3600+7200)/2


# ---------------------------------------------------------------------------
# oura_summary_table
# ---------------------------------------------------------------------------


@respx.mock
async def test_summary_table_basic():
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=SLEEP_FIXTURE))
    respx.get(f"{BASE_URL}/daily_sleep").mock(
        return_value=httpx.Response(200, json=DAILY_SLEEP_FIXTURE)
    )
    respx.get(f"{BASE_URL}/daily_readiness").mock(
        return_value=httpx.Response(200, json=DAILY_READINESS_FIXTURE)
    )
    respx.get(f"{BASE_URL}/daily_spo2").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    result = await _call("oura_summary_table", start_date="2026-04-27", end_date="2026-04-28")

    assert len(result["data"]) == 2
    row = result["data"][1]  # Apr 28
    assert row["date"] == "2026-04-28"
    assert row["deep_min"] == 90   # 5400s → 90 min
    assert row["rem_min"] == 120   # 7200s → 120 min
    assert row["efficiency"] == 93
    assert row["hrv"] == 45
    assert row["rhr"] == 50
    assert row["sleep_score"] == 85
    assert row["readiness_score"] == 81


@respx.mock
async def test_summary_table_missing_day_nulls():
    """A day with no sleep session should produce null metrics."""
    respx.get(f"{BASE_URL}/sleep").mock(
        return_value=httpx.Response(200, json={"data": [], "next_token": None})
    )
    respx.get(f"{BASE_URL}/daily_sleep").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get(f"{BASE_URL}/daily_readiness").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    respx.get(f"{BASE_URL}/daily_spo2").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    result = await _call("oura_summary_table", start_date="2026-04-28", end_date="2026-04-28")
    row = result["data"][0]
    assert row["date"] == "2026-04-28"
    assert row["deep_min"] is None
    assert row["sleep_score"] is None
