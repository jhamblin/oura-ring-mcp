"""Direct API mirror tools — one MCP tool per Oura v2 usercollection endpoint.

Each tool resolves the PAT, opens an OuraClient, and returns the raw JSON.
Errors are translated to a structured envelope by the @safe_tool decorator
so callers can branch on `result.get("error")` rather than catching exceptions.

More tools land here in spec §10 steps 3, 4, and 8.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from .._dates import resolve_date_params
from .._errors import safe_tool
from ..auth import resolve_pat
from ..client import OuraClient


def register(mcp: FastMCP) -> None:
    """Attach all direct-API tools to the given FastMCP instance."""

    # ------------------------------------------------------------------
    # Connectivity / profile
    # ------------------------------------------------------------------

    @mcp.tool()
    @safe_tool
    async def oura_personal_info(pat: str | None = None) -> dict[str, Any]:
        """Return the user's Oura profile (sex, age, height, weight, email).

        Endpoint: /v2/usercollection/personal_info. No date params.
        Useful as a connectivity check.
        """
        async with OuraClient(resolve_pat(pat)) as client:
            return await client.get("personal_info")

    # ------------------------------------------------------------------
    # Daily-score endpoints (step 3)
    # Each returns {"data": [...]} — one document per day.
    # These do not paginate; a full year is ≤365 records.
    # ------------------------------------------------------------------

    @mcp.tool()
    @safe_tool
    async def oura_daily_sleep(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return Oura daily sleep scores for a date or range.

        Endpoint: /v2/usercollection/daily_sleep.

        Returns the Oura sleep score (0–100) and contributor breakdown per day
        (deep_sleep, efficiency, latency, rem_sleep, restfulness, timing, total_sleep).
        These are opaque 0–100 algorithm scores — for raw period data (actual minutes,
        hypnogram, HRV) use oura_sleep instead.

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today. Mutually exclusive with
                    start_date/end_date.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.
        """
        params = resolve_date_params(date, start_date, end_date)
        async with OuraClient(resolve_pat(pat)) as client:
            return await client.get("daily_sleep", params)

    @mcp.tool()
    @safe_tool
    async def oura_daily_readiness(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return Oura daily readiness scores for a date or range.

        Endpoint: /v2/usercollection/daily_readiness.

        Returns the readiness score (0–100), contributors (activity_balance,
        body_temperature, hrv_balance, previous_day_activity, previous_night,
        recovery_index, resting_heart_rate, sleep_balance), and
        temperature_deviation (°C from baseline).

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.
        """
        params = resolve_date_params(date, start_date, end_date)
        async with OuraClient(resolve_pat(pat)) as client:
            return await client.get("daily_readiness", params)

    @mcp.tool()
    @safe_tool
    async def oura_daily_activity(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return Oura daily activity summaries for a date or range.

        Endpoint: /v2/usercollection/daily_activity.

        Returns steps, active_calories, total_calories, equivalent_walking_distance,
        high/medium/low activity minutes, MET minutes, inactivity_alerts,
        and the activity score with contributors.

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.
        """
        params = resolve_date_params(date, start_date, end_date)
        async with OuraClient(resolve_pat(pat)) as client:
            return await client.get("daily_activity", params)

    @mcp.tool()
    @safe_tool
    async def oura_daily_spo2(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return Oura daily SpO2 (blood oxygen) averages for a date or range.

        Endpoint: /v2/usercollection/daily_spo2.

        Returns spo2_percentage.average and breathing_disturbance_index per day.
        May return empty data for Gen 2 devices or nights with insufficient data.

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.
        """
        params = resolve_date_params(date, start_date, end_date)
        async with OuraClient(resolve_pat(pat)) as client:
            return await client.get("daily_spo2", params)

    # ------------------------------------------------------------------
    # Sleep periods (step 4) — the critical missing piece
    # ------------------------------------------------------------------

    @mcp.tool()
    @safe_tool
    async def oura_sleep(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return all sleep periods (long_sleep + naps) for a date or range.

        Endpoint: /v2/usercollection/sleep.

        This is the primary data tool — it returns actual period-level data that
        the daily-score endpoints omit: deep/REM/light/awake durations in seconds,
        sleep_phase_5_min (hypnogram), average_hrv, lowest_heart_rate, average_breath,
        restless_periods, latency, efficiency, time-series heart_rate and hrv, and more.

        **Overnight buffer (spec §7):** Oura filters /sleep by bedtime_start, not by
        the logical day field. A sleep starting at 11:30pm on Apr 12 has day=Apr 13
        (the wake date). This tool automatically expands the fetch range by ±1 day and
        filters results in memory by the day field, so overnight sleeps are never missed.

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today. Mutually exclusive with
                    start_date/end_date.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.

        Returns
        -------
        {"data": [...]} — one dict per sleep period. Each includes type ("long_sleep",
        "rest", etc.), day, bedtime_start, bedtime_end, and full sleep metrics.
        """
        params = resolve_date_params(date, start_date, end_date)
        req_start = params["start_date"]
        req_end = params["end_date"]

        # Apply the ±1 day buffer so that overnight sleeps whose bedtime_start
        # is the prior calendar day are not missed (spec §7).
        buf_start = (datetime.strptime(req_start, "%Y-%m-%d") - timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )
        buf_end = (datetime.strptime(req_end, "%Y-%m-%d") + timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )
        buf_params = {"start_date": buf_start, "end_date": buf_end}

        async with OuraClient(resolve_pat(pat)) as client:
            all_sessions = await client.get_all("sleep", buf_params)

        # Filter to sessions whose logical day is within the originally requested range.
        filtered = [s for s in all_sessions if req_start <= s["day"] <= req_end]
        return {"data": filtered}
