"""Tests for the file-based local cache (spec §8)."""

from __future__ import annotations

import json
from datetime import date

import httpx
import respx

from oura_mcp import cache as cache_mod
from oura_mcp.cache import cache_read, cache_write, is_today, resolve_cache_dir
from oura_mcp.client import BASE_URL
from oura_mcp.server import mcp

_tools = {t.name: t for t in mcp._tool_manager.list_tools()}


# ---------------------------------------------------------------------------
# Unit: cache primitives
# ---------------------------------------------------------------------------


def test_is_today_true():
    assert is_today(date.today().isoformat()) is True


def test_is_today_false():
    assert is_today("2020-01-01") is False


def test_resolve_cache_dir_unset(monkeypatch):
    monkeypatch.delenv(cache_mod.CACHE_DIR_ENV, raising=False)
    assert resolve_cache_dir() is None


def test_resolve_cache_dir_set(monkeypatch, tmp_path):
    monkeypatch.setenv(cache_mod.CACHE_DIR_ENV, str(tmp_path))
    assert resolve_cache_dir() == tmp_path


def test_resolve_cache_dir_expands_user(monkeypatch):
    monkeypatch.setenv(cache_mod.CACHE_DIR_ENV, "~/.oura-mcp/raw")
    result = resolve_cache_dir()
    assert not str(result).startswith("~")


def test_cache_write_creates_file(tmp_path):
    data = {"date": "2026-04-20", "sleep_sessions": []}
    cache_write(tmp_path, "2026-04-20", data)
    written = json.loads((tmp_path / "2026-04-20.json").read_text())
    assert written == data


def test_cache_write_creates_dirs(tmp_path):
    nested = tmp_path / "a" / "b"
    cache_write(nested, "2026-04-20", {"date": "2026-04-20"})
    assert (nested / "2026-04-20.json").exists()


def test_cache_write_overwrites(tmp_path):
    cache_write(tmp_path, "2026-04-20", {"date": "2026-04-20", "v": 1})
    cache_write(tmp_path, "2026-04-20", {"date": "2026-04-20", "v": 2})
    assert json.loads((tmp_path / "2026-04-20.json").read_text())["v"] == 2


def test_cache_read_hit(tmp_path):
    data = {"date": "2026-04-20", "sleep_sessions": [{"id": "s1"}]}
    (tmp_path / "2026-04-20.json").write_text(json.dumps(data))
    assert cache_read(tmp_path, "2026-04-20") == data


def test_cache_read_miss(tmp_path):
    assert cache_read(tmp_path, "2026-04-20") is None


def test_cache_read_today_always_none(tmp_path):
    today = date.today().isoformat()
    cache_write(tmp_path, today, {"date": today})
    # Even though the file exists, today is never served from cache.
    assert cache_read(tmp_path, today) is None


def test_cache_read_corrupted_file(tmp_path):
    (tmp_path / "2026-04-20.json").write_text("not valid json{{{")
    assert cache_read(tmp_path, "2026-04-20") is None


# ---------------------------------------------------------------------------
# Fixtures for integration tests
# ---------------------------------------------------------------------------

SLEEP_FIXTURE = {
    "data": [
        {
            "id": "s1",
            "type": "long_sleep",
            "day": "2026-04-20",
            "bedtime_start": "2026-04-20T00:05:00-07:00",
            "total_sleep_duration": 25200,
            "deep_sleep_duration": 5400,
            "rem_sleep_duration": 7200,
            "light_sleep_duration": 12600,
            "awake_time": 900,
            "efficiency": 93,
            "average_hrv": 45,
            "lowest_heart_rate": 50,
        }
    ],
    "next_token": None,
}

DAILY_SLEEP_FIXTURE = {"data": [{"day": "2026-04-20", "score": 85}]}
DAILY_READINESS_FIXTURE = {"data": [{"day": "2026-04-20", "score": 81}]}
DAILY_SPO2_FIXTURE = {"data": [{"day": "2026-04-20", "spo2_percentage": {"average": 97.2}}]}


# ---------------------------------------------------------------------------
# Integration: oura_summary_table with cache disabled
# ---------------------------------------------------------------------------


@respx.mock
async def test_summary_table_cache_disabled(monkeypatch):
    monkeypatch.delenv(cache_mod.CACHE_DIR_ENV, raising=False)
    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=SLEEP_FIXTURE))
    respx.get(f"{BASE_URL}/daily_sleep").mock(return_value=httpx.Response(200, json=DAILY_SLEEP_FIXTURE))
    respx.get(f"{BASE_URL}/daily_readiness").mock(return_value=httpx.Response(200, json=DAILY_READINESS_FIXTURE))
    respx.get(f"{BASE_URL}/daily_spo2").mock(return_value=httpx.Response(200, json=DAILY_SPO2_FIXTURE))

    result = await _tools["oura_summary_table"].fn(
        start_date="2026-04-20", end_date="2026-04-20", pat="test-token"
    )
    assert result["data"][0]["cache_status"] == "disabled"


# ---------------------------------------------------------------------------
# Integration: oura_summary_table with cache enabled
# ---------------------------------------------------------------------------


@respx.mock
async def test_summary_table_cache_miss_then_hit(monkeypatch, tmp_path):
    monkeypatch.setenv(cache_mod.CACHE_DIR_ENV, str(tmp_path))

    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=SLEEP_FIXTURE))
    respx.get(f"{BASE_URL}/daily_sleep").mock(return_value=httpx.Response(200, json=DAILY_SLEEP_FIXTURE))
    respx.get(f"{BASE_URL}/daily_readiness").mock(return_value=httpx.Response(200, json=DAILY_READINESS_FIXTURE))
    respx.get(f"{BASE_URL}/daily_spo2").mock(return_value=httpx.Response(200, json=DAILY_SPO2_FIXTURE))

    # First call → cache miss, should fetch and write.
    result1 = await _tools["oura_summary_table"].fn(
        start_date="2026-04-20", end_date="2026-04-20", pat="test-token"
    )
    assert result1["data"][0]["cache_status"] == "miss"
    assert (tmp_path / "2026-04-20.json").exists()


@respx.mock
async def test_summary_table_cache_hit_no_api_call(monkeypatch, tmp_path):
    monkeypatch.setenv(cache_mod.CACHE_DIR_ENV, str(tmp_path))

    # Pre-populate cache.
    cached_day = {
        "date": "2026-04-20",
        "sleep_sessions": SLEEP_FIXTURE["data"],
        "daily_sleep": DAILY_SLEEP_FIXTURE["data"][0],
        "daily_readiness": DAILY_READINESS_FIXTURE["data"][0],
        "daily_spo2": DAILY_SPO2_FIXTURE["data"][0],
    }
    cache_write(tmp_path, "2026-04-20", cached_day)

    # No API routes registered — any real call would raise.
    result = await _tools["oura_summary_table"].fn(
        start_date="2026-04-20", end_date="2026-04-20", pat="test-token"
    )
    assert result["data"][0]["cache_status"] == "hit"
    assert result["data"][0]["deep_min"] == 90
    assert result["data"][0]["sleep_score"] == 85


@respx.mock
async def test_summary_table_partial_cache_hit(monkeypatch, tmp_path):
    """Apr 20 cached, Apr 21 not — only Apr 21 should hit the API."""
    monkeypatch.setenv(cache_mod.CACHE_DIR_ENV, str(tmp_path))

    sleep_21 = {
        "data": [
            {
                "id": "s2",
                "type": "long_sleep",
                "day": "2026-04-21",
                "bedtime_start": "2026-04-21T00:10:00-07:00",
                "total_sleep_duration": 23400,
                "deep_sleep_duration": 3600,
                "rem_sleep_duration": 6000,
                "light_sleep_duration": 13800,
                "awake_time": 1200,
                "efficiency": 90,
                "average_hrv": 40,
                "lowest_heart_rate": 52,
            }
        ],
        "next_token": None,
    }

    cached_day = {
        "date": "2026-04-20",
        "sleep_sessions": SLEEP_FIXTURE["data"],
        "daily_sleep": DAILY_SLEEP_FIXTURE["data"][0],
        "daily_readiness": DAILY_READINESS_FIXTURE["data"][0],
        "daily_spo2": None,
    }
    cache_write(tmp_path, "2026-04-20", cached_day)

    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=sleep_21))
    respx.get(f"{BASE_URL}/daily_sleep").mock(return_value=httpx.Response(200, json={"data": [{"day": "2026-04-21", "score": 78}]}))
    respx.get(f"{BASE_URL}/daily_readiness").mock(return_value=httpx.Response(200, json={"data": [{"day": "2026-04-21", "score": 72}]}))
    respx.get(f"{BASE_URL}/daily_spo2").mock(return_value=httpx.Response(200, json={"data": []}))

    result = await _tools["oura_summary_table"].fn(
        start_date="2026-04-20", end_date="2026-04-21", pat="test-token"
    )
    rows = {r["date"]: r for r in result["data"]}
    assert rows["2026-04-20"]["cache_status"] == "hit"
    assert rows["2026-04-21"]["cache_status"] == "miss"


# ---------------------------------------------------------------------------
# Integration: oura_cache_rebuild
# ---------------------------------------------------------------------------


@respx.mock
async def test_cache_rebuild_not_configured(monkeypatch):
    monkeypatch.delenv(cache_mod.CACHE_DIR_ENV, raising=False)
    result = await _tools["oura_cache_rebuild"].fn(
        start_date="2026-04-20", end_date="2026-04-20", pat="test-token"
    )
    assert result["error"] == "cache_not_configured"


@respx.mock
async def test_cache_rebuild_force_refreshes(monkeypatch, tmp_path):
    monkeypatch.setenv(cache_mod.CACHE_DIR_ENV, str(tmp_path))

    # Pre-populate with stale data.
    stale = {"date": "2026-04-20", "sleep_sessions": [], "daily_sleep": None,
             "daily_readiness": None, "daily_spo2": None}
    cache_write(tmp_path, "2026-04-20", stale)

    respx.get(f"{BASE_URL}/sleep").mock(return_value=httpx.Response(200, json=SLEEP_FIXTURE))
    respx.get(f"{BASE_URL}/daily_sleep").mock(return_value=httpx.Response(200, json=DAILY_SLEEP_FIXTURE))
    respx.get(f"{BASE_URL}/daily_readiness").mock(return_value=httpx.Response(200, json=DAILY_READINESS_FIXTURE))
    respx.get(f"{BASE_URL}/daily_spo2").mock(return_value=httpx.Response(200, json=DAILY_SPO2_FIXTURE))

    result = await _tools["oura_cache_rebuild"].fn(
        start_date="2026-04-20", end_date="2026-04-20", pat="test-token"
    )
    assert result["count"] == 1
    assert "2026-04-20" in result["rebuilt"]

    # Cache file should now have the fresh sleep session.
    refreshed = json.loads((tmp_path / "2026-04-20.json").read_text())
    assert len(refreshed["sleep_sessions"]) == 1
