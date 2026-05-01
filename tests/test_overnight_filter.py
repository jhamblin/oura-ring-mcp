"""Regression tests for the overnight-sleep buffer trick (spec §7).

The Oura /sleep endpoint filters by bedtime_start, not by the logical day field.
A sleep starting at 11:30pm on Apr 12 has bedtime_start=2026-04-12 but day=2026-04-13
(the wake date — Oura's convention). Without the 1-day buffer, requesting Apr 13
would miss this session entirely.

The fixture at tests/fixtures/sleep_response.json contains:
  - Session 1: day=Apr 12, bedtime_start=Apr 12 00:15 (same-day, no edge case)
  - Session 2: day=Apr 13, bedtime_start=Apr 12 23:30 (THE overnight edge case)
  - Session 3: day=Apr 14, bedtime_start=Apr 14 00:05 (same-day)
  - Session 4: day=Apr 13, type=rest (nap, same day — not the edge case but
               verifies naps are included when their day matches)

These tests MUST FAIL if the buffer is removed — that's the regression guarantee.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import respx

from oura_ring_mcp.client import BASE_URL
from oura_ring_mcp.server import mcp

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "sleep_response.json").read_text())

_tools = {t.name: t for t in mcp._tool_manager.list_tools()}


async def _call_sleep(**kwargs):
    kwargs.setdefault("pat", "test-token")
    return await _tools["oura_sleep"].fn(**kwargs)


# ------------------------------------------------------------------
# Core overnight-buffer regression
# ------------------------------------------------------------------


@respx.mock
async def test_overnight_session_found_when_requesting_wake_date():
    """Session 2 has day=Apr 13 but bedtime_start=Apr 12.
    A naive fetch for Apr 13 only would miss it. The buffer must catch it.
    """
    # The buffer should expand Apr 13 → fetch Apr 12..Apr 14.
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=FIXTURE))

    result = await _call_sleep(date="2026-04-13")
    days = [s["day"] for s in result["data"]]

    assert "2026-04-13" in days, "Overnight session with day=Apr 13 must be returned"
    # Session 2 specifically:
    assert any(
        s["day"] == "2026-04-13" and s["bedtime_start"].startswith("2026-04-12")
        for s in result["data"]
    ), "The overnight-crossing session (bedtime_start on prior day) must be present"


@respx.mock
async def test_overnight_session_excluded_from_prior_date():
    """When requesting Apr 12, session 2 (day=Apr 13) must NOT appear."""
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=FIXTURE))

    result = await _call_sleep(date="2026-04-12")
    days = [s["day"] for s in result["data"]]

    assert "2026-04-13" not in days, "Sessions with day=Apr 13 must not appear in an Apr 12 request"


@respx.mock
async def test_buffer_expands_fetch_range():
    """Verify that the API call uses start_date-1 and end_date+1."""
    route = respx.get(f"{BASE_URL}/sleep").mock(
        return_value=httpx.Response(200, json={"data": [], "next_token": None})
    )

    await _call_sleep(start_date="2026-04-13", end_date="2026-04-15")

    # Inspect the actual query params sent to the API.
    req = route.calls[0].request
    url_str = str(req.url)
    assert "start_date=2026-04-12" in url_str, "Buffer must subtract 1 day from start"
    assert "end_date=2026-04-16" in url_str, "Buffer must add 1 day to end"


# ------------------------------------------------------------------
# Day filtering correctness
# ------------------------------------------------------------------


@respx.mock
async def test_range_includes_all_matching_days():
    """Apr 12–14 should include sessions for all three days."""
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=FIXTURE))

    result = await _call_sleep(start_date="2026-04-12", end_date="2026-04-14")
    days = sorted({s["day"] for s in result["data"]})
    assert days == ["2026-04-12", "2026-04-13", "2026-04-14"]


@respx.mock
async def test_nap_included_when_day_matches():
    """Session 4 is a nap (type=rest) on Apr 13. It should be returned for Apr 13."""
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=FIXTURE))

    result = await _call_sleep(date="2026-04-13")
    types = [s["type"] for s in result["data"]]
    assert "rest" in types, "Naps with matching day should be included"


@respx.mock
async def test_range_boundary_exclusion():
    """Apr 14 only — should not include any Apr 13 sessions."""
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=FIXTURE))

    result = await _call_sleep(date="2026-04-14")
    days = [s["day"] for s in result["data"]]
    assert all(d == "2026-04-14" for d in days)
    assert len(result["data"]) == 1


# ------------------------------------------------------------------
# Error envelope
# ------------------------------------------------------------------


@respx.mock
async def test_sleep_error_envelope():
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(401, text="Unauthorized"))
    result = await _call_sleep(date="2026-04-13")
    assert result["error"] == "oura_api_error"
    assert result["status"] == 401


# ------------------------------------------------------------------
# Null-day guard (real-world defensive fix)
# ------------------------------------------------------------------


@respx.mock
async def test_null_day_session_excluded():
    """Sessions with day=None must be silently skipped, not cause a TypeError."""
    fixture_with_null = {
        "data": [
            {"id": "s1", "type": "long_sleep", "day": None,
             "bedtime_start": "2026-04-12T23:00:00-07:00", "total_sleep_duration": 25200},
            {"id": "s2", "type": "long_sleep", "day": "2026-04-13",
             "bedtime_start": "2026-04-13T00:05:00-07:00", "total_sleep_duration": 25200},
        ],
        "next_token": None,
    }
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=fixture_with_null))
    result = await _call_sleep(date="2026-04-13")
    assert "error" not in result
    assert len(result["data"]) == 1
    assert result["data"][0]["day"] == "2026-04-13"
