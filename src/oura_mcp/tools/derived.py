"""Derived tools — computed results built on top of the direct API tools (spec §5.2).

All derived tools are thin wrappers over the client — no business logic that
diverges from raw Oura semantics (per spec). They use the same overnight buffer
and primary-session selection logic as the reference implementation.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from .._dates import resolve_date_params
from .._errors import safe_tool
from ..auth import resolve_pat
from ..cache import cache_read, cache_write, resolve_cache_dir
from ..client import OuraClient

# ---------------------------------------------------------------------------
# Hypnogram character mapping — matches reference implementation (oura_fetch.py)
# ---------------------------------------------------------------------------

_HYPNO_CHARS: dict[str, str] = {"1": "█", "2": "░", "3": "▒", "4": "·"}
HYPNO_KEY = "█=deep  ░=light  ▒=REM  ·=awake  (each char = 5 min)"


# ---------------------------------------------------------------------------
# Internal helpers (shared across derived tools)
# ---------------------------------------------------------------------------


def _render_hypnogram(phase_5min: str, chars_per_5min: int = 1) -> str:
    """Convert Oura sleep_phase_5_min to an ASCII stage timeline."""
    if not phase_5min:
        return "—"
    return "".join(_HYPNO_CHARS.get(c, "?") * chars_per_5min for c in phase_5min)


def _primary_session(sessions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the primary sleep session for a day.

    Mirrors the reference implementation: prefer long_sleep type; fall back to
    the longest session of any type. Returns None if sessions is empty.
    """
    if not sessions:
        return None
    long = [s for s in sessions if s.get("type") == "long_sleep"]
    pool = long if long else sessions
    return max(pool, key=lambda s: s.get("total_sleep_duration") or 0)


def _extract_metric(session: dict[str, Any], metric: str) -> float | None:
    """Pull a named numeric field from a session dict, or None if absent."""
    val = session.get(metric)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


async def _fetch_sleep_by_day(
    client: OuraClient,
    req_start: str,
    req_end: str,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch sleep sessions with the overnight buffer, grouped by logical day.

    Returns a dict keyed by YYYY-MM-DD with a list of sessions per day.
    """
    buf_start = (datetime.strptime(req_start, "%Y-%m-%d") - timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )
    buf_end = (datetime.strptime(req_end, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    all_sessions = await client.get_all("sleep", {"start_date": buf_start, "end_date": buf_end})
    by_day: dict[str, list[dict[str, Any]]] = {}
    for s in all_sessions:
        if req_start <= s["day"] <= req_end:
            by_day.setdefault(s["day"], []).append(s)
    return by_day


def _date_range(start: str, end: str) -> list[str]:
    """Return every YYYY-MM-DD string between start and end inclusive."""
    current = datetime.strptime(start, "%Y-%m-%d")
    stop = datetime.strptime(end, "%Y-%m-%d")
    dates = []
    while current <= stop:
        dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


def _percentile_nearest_rank(sorted_data: list[float], p: int) -> float:
    """Compute the p-th percentile using the nearest-rank (ceiling) method."""
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]
    idx = max(0, min(n - 1, math.ceil(p / 100 * n) - 1))
    return sorted_data[idx]


def _secs_to_min(secs: int | float | None) -> int | None:
    """Convert seconds to whole minutes, or None."""
    return round(secs / 60) if secs is not None else None


async def fetch_summary_range(
    client: OuraClient,
    req_start: str,
    req_end: str,
    force_refresh: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Fetch per-day summary data for a range, using the local cache when available.

    Returns:
        day_data:  {date: {"sleep_sessions": [...], "daily_sleep": {...}, ...}}
        statuses:  {date: "hit" | "miss" | "disabled"}

    Cache behaviour:
    - "hit"      → served from cache file; no API call for that day.
    - "miss"     → fetched from API and written to cache.
    - "disabled" → OURA_MCP_CACHE_DIR not set; always fetches, never writes.

    All uncached days are fetched in a single batched API request. force_refresh=True
    skips cache reads but still writes (used by oura_cache_rebuild).
    """
    cache_dir = resolve_cache_dir()
    dates = _date_range(req_start, req_end)
    day_data: dict[str, dict[str, Any]] = {}
    statuses: dict[str, str] = {}

    # 1. Check cache for each day.
    cache_misses: list[str] = []
    for day in dates:
        if cache_dir and not force_refresh:
            cached = cache_read(cache_dir, day)
            if cached is not None:
                day_data[day] = cached
                statuses[day] = "hit"
                continue
        statuses[day] = "disabled" if not cache_dir else "miss"
        cache_misses.append(day)

    if not cache_misses:
        return day_data, statuses

    # 2. Batch-fetch all missed days in one round of API calls.
    miss_start = min(cache_misses)
    miss_end = max(cache_misses)
    date_params = {"start_date": miss_start, "end_date": miss_end}

    sleep_by_day, ds_resp, dr_resp, spo2_resp = await asyncio.gather(
        _fetch_sleep_by_day(client, miss_start, miss_end),
        client.get("daily_sleep", date_params),
        client.get("daily_readiness", date_params),
        client.get("daily_spo2", date_params),
    )

    daily_sleep = {d["day"]: d for d in ds_resp.get("data", [])}
    daily_readiness = {d["day"]: d for d in dr_resp.get("data", [])}
    daily_spo2 = {d["day"]: d for d in spo2_resp.get("data", [])}

    # 3. Assemble per-day dicts and write to cache.
    for day in cache_misses:
        data: dict[str, Any] = {
            "date": day,
            "sleep_sessions": sleep_by_day.get(day, []),
            "daily_sleep": daily_sleep.get(day),
            "daily_readiness": daily_readiness.get(day),
            "daily_spo2": daily_spo2.get(day),
        }
        day_data[day] = data
        if cache_dir:
            cache_write(cache_dir, day, data)

    return day_data, statuses


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Attach all derived tools to the given FastMCP instance."""

    @mcp.tool()
    @safe_tool
    async def oura_render_hypnogram(
        date: str | None = None,
        chars_per_5min: int = 1,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Render an ASCII hypnogram for the primary sleep session on a given date.

        Each character represents 5 minutes of sleep. Uses the sleep_phase_5_min
        field from the primary long_sleep session.

        Character key:
          █ = deep sleep
          ░ = light sleep
          ▒ = REM sleep
          · = awake

        Parameters
        ----------
        date:           YYYY-MM-DD. Defaults to today.
        chars_per_5min: Characters per 5-minute interval (default 1). Set to 2 for
                        a wider chart.
        pat:            Override the resolved PAT for this call only.

        Returns
        -------
        {
          "date": "YYYY-MM-DD",
          "hypnogram": "█████░░░▒▒▒░░░...",
          "key": "█=deep  ░=light  ▒=REM  ·=awake  (each char = 5 min)",
          "session_type": "long_sleep",
          "total_minutes": 412
        }
        """
        params = resolve_date_params(date, None, None)
        day = params["start_date"]

        async with OuraClient(resolve_pat(pat)) as client:
            by_day = await _fetch_sleep_by_day(client, day, day)

        sessions = by_day.get(day, [])
        primary = _primary_session(sessions)

        if not primary:
            return {"date": day, "hypnogram": None, "key": HYPNO_KEY, "error": "no_data"}

        phase = primary.get("sleep_phase_5_min", "")
        return {
            "date": day,
            "hypnogram": _render_hypnogram(phase, chars_per_5min),
            "key": HYPNO_KEY,
            "session_type": primary.get("type"),
            "total_minutes": _secs_to_min(primary.get("total_sleep_duration")),
        }

    @mcp.tool()
    @safe_tool
    async def oura_percentiles(
        metric: str,
        start_date: str | None = None,
        end_date: str | None = None,
        percentiles: list[int] | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Compute percentiles for a sleep metric over a date range.

        Operates on the primary long_sleep session per day. Days with no session
        or a missing metric value are excluded from the calculation.

        Common metrics: deep_sleep_duration, rem_sleep_duration, light_sleep_duration,
        total_sleep_duration, awake_time, efficiency, average_hrv, lowest_heart_rate,
        latency, restless_periods, average_breath.

        Parameters
        ----------
        metric:      Field name on the sleep session object.
        start_date:  Range start YYYY-MM-DD. Defaults to today.
        end_date:    Range end YYYY-MM-DD. Defaults to today.
        percentiles: List of integer percentile values to compute (default [50,75,95]).
        pat:         Override the resolved PAT for this call only.

        Returns
        -------
        {
          "metric": "deep_sleep_duration",
          "start_date": "...", "end_date": "...",
          "count": 30,
          "min": 1800, "max": 7200,
          "mean": 3420.0,
          "percentiles": {"50": 3300, "75": 4500, "95": 6300}
        }
        """
        if percentiles is None:
            percentiles = [50, 75, 95]

        params = resolve_date_params(None, start_date, end_date)
        req_start, req_end = params["start_date"], params["end_date"]

        async with OuraClient(resolve_pat(pat)) as client:
            by_day = await _fetch_sleep_by_day(client, req_start, req_end)

        values: list[float] = []
        for sessions in by_day.values():
            primary = _primary_session(sessions)
            if primary:
                v = _extract_metric(primary, metric)
                if v is not None:
                    values.append(v)

        if not values:
            return {
                "metric": metric,
                "start_date": req_start,
                "end_date": req_end,
                "count": 0,
                "error": "no_data",
            }

        values.sort()
        return {
            "metric": metric,
            "start_date": req_start,
            "end_date": req_end,
            "count": len(values),
            "min": values[0],
            "max": values[-1],
            "mean": round(sum(values) / len(values), 2),
            "percentiles": {
                str(p): _percentile_nearest_rank(values, p) for p in percentiles
            },
        }

    @mcp.tool()
    @safe_tool
    async def oura_rolling_average(
        metric: str,
        start_date: str | None = None,
        end_date: str | None = None,
        window: int = 7,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Compute a rolling average for a sleep metric over a date range.

        Returns one row per day. Days with no session have value=null and are
        excluded from the rolling window calculation (the window spans only
        days with data).

        Parameters
        ----------
        metric:     Field name on the sleep session object.
        start_date: Range start YYYY-MM-DD. Defaults to today.
        end_date:   Range end YYYY-MM-DD. Defaults to today.
        window:     Rolling window size in days (default 7).
        pat:        Override the resolved PAT for this call only.

        Returns
        -------
        {
          "metric": "deep_sleep_duration",
          "window": 7,
          "data": [
            {"date": "2026-04-01", "value": 3600, "rolling_avg": 3420.0},
            {"date": "2026-04-02", "value": null, "rolling_avg": null},
            ...
          ]
        }
        """
        params = resolve_date_params(None, start_date, end_date)
        req_start, req_end = params["start_date"], params["end_date"]

        async with OuraClient(resolve_pat(pat)) as client:
            by_day = await _fetch_sleep_by_day(client, req_start, req_end)

        dates = _date_range(req_start, req_end)

        # Build (date, value) pairs — None where data is missing.
        daily: list[tuple[str, float | None]] = []
        for day in dates:
            sessions = by_day.get(day, [])
            primary = _primary_session(sessions)
            val = _extract_metric(primary, metric) if primary else None
            daily.append((day, val))

        # Compute rolling average using only non-None values within each window.
        rows = []
        for i, (day, val) in enumerate(daily):
            window_start = max(0, i - window + 1)
            window_vals = [v for _, v in daily[window_start : i + 1] if v is not None]
            rolling = round(sum(window_vals) / len(window_vals), 2) if window_vals else None
            rows.append({"date": day, "value": val, "rolling_avg": rolling})

        return {"metric": metric, "window": window, "data": rows}

    @mcp.tool()
    @safe_tool
    async def oura_summary_table(
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return a compact per-night summary joining sleep, readiness, and scores.

        Fetches oura_sleep + oura_daily_sleep + oura_daily_readiness in parallel
        and joins them by day. One row per night, ~200 tokens per night.

        This is the highest-value tool for analysis workflows — use it as the
        starting point before drilling into specific nights with oura_sleep.

        Parameters
        ----------
        start_date: Range start YYYY-MM-DD. Defaults to today.
        end_date:   Range end YYYY-MM-DD. Defaults to today.
        pat:        Override the resolved PAT for this call only.

        Returns
        -------
        {
          "data": [
            {
              "date": "2026-04-28",
              "deep_min": 65, "rem_min": 102, "light_min": 241, "awake_min": 18,
              "efficiency": 91, "hrv": 42, "rhr": 52,
              "sleep_score": 82, "readiness_score": 79
            },
            ...
          ]
        }
        """
        params = resolve_date_params(None, start_date, end_date)
        req_start, req_end = params["start_date"], params["end_date"]

        async with OuraClient(resolve_pat(pat)) as client:
            day_data, statuses = await fetch_summary_range(client, req_start, req_end)

        rows = []
        for day in _date_range(req_start, req_end):
            data = day_data.get(day, {})
            primary = _primary_session(data.get("sleep_sessions", []))
            ds = data.get("daily_sleep") or {}
            dr = data.get("daily_readiness") or {}

            row: dict[str, Any] = {"date": day, "cache_status": statuses.get(day, "disabled")}
            if primary:
                row["deep_min"] = _secs_to_min(primary.get("deep_sleep_duration"))
                row["rem_min"] = _secs_to_min(primary.get("rem_sleep_duration"))
                row["light_min"] = _secs_to_min(primary.get("light_sleep_duration"))
                row["awake_min"] = _secs_to_min(primary.get("awake_time"))
                row["efficiency"] = primary.get("efficiency")
                row["hrv"] = primary.get("average_hrv")
                row["rhr"] = primary.get("lowest_heart_rate")
            else:
                row.update(
                    deep_min=None, rem_min=None, light_min=None,
                    awake_min=None, efficiency=None, hrv=None, rhr=None,
                )

            row["sleep_score"] = ds.get("score") if ds else None
            row["readiness_score"] = dr.get("score") if dr else None
            rows.append(row)

        return {"data": rows}
