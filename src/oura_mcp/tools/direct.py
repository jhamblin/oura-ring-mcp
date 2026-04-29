"""Direct API mirror tools — one MCP tool per Oura v2 usercollection endpoint.

Each tool resolves the PAT, opens an OuraClient, and returns the raw JSON.
Errors are translated to a structured envelope by the @safe_tool decorator
so callers can branch on `result.get("error")` rather than catching exceptions.

More tools land here in spec §10 steps 3, 4, and 8.
"""

from __future__ import annotations

from datetime import date as _date, datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from .._dates import resolve_date_params
from .._errors import safe_tool
from ..auth import resolve_pat
from ..client import OuraAPIError, OuraClient
from .compaction import _summarize_items
from .compaction import compact_sleep_sessions


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
        format: str = "compact",
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

        **Output modes (spec §6):**
        - format="compact" (default): Drops bulky time-series (heart_rate.items,
          hrv.items, sleep_phase_30_sec, movement_30_sec) and replaces HR/HRV with
          {min, max, avg, samples} summaries. Keeps sleep_phase_5_min for hypnogram.
        - format="full": Returns the unmodified Oura response. Caller is responsible
          for context budget.

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today. Mutually exclusive with
                    start_date/end_date.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        format:     "compact" (default) or "full". See output modes above.
        pat:        Override the resolved PAT for this call only.

        Returns
        -------
        {"data": [...]} — one dict per sleep period. Each includes type ("long_sleep",
        "rest", etc.), day, bedtime_start, bedtime_end, and sleep metrics.
        In compact mode, heart_rate and hrv contain summaries instead of raw items.
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

        if format == "compact":
            filtered = compact_sleep_sessions(filtered)

        return {"data": filtered}

    # ------------------------------------------------------------------
    # Remaining daily-score endpoints (step 8, Gen 3+)
    # ------------------------------------------------------------------

    @mcp.tool()
    @safe_tool
    async def oura_daily_stress(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return Oura daily stress summaries for a date or range.

        Endpoint: /v2/usercollection/daily_stress. Gen 3+ only; may return
        empty data for older devices.

        Returns stress_high, stress_medium, stress_low, recovery_high,
        recovery_medium, recovery_low durations in seconds, plus day_summary.

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.
        """
        params = resolve_date_params(date, start_date, end_date)
        async with OuraClient(resolve_pat(pat)) as client:
            return await client.get("daily_stress", params)

    @mcp.tool()
    @safe_tool
    async def oura_daily_resilience(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return Oura daily resilience scores for a date or range.

        Endpoint: /v2/usercollection/daily_resilience. Gen 3+ only.

        Returns level (exceptional/strong/adequate/limited/poor) and
        contributors (sleep_recovery, daytime_recovery, stress).

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.
        """
        params = resolve_date_params(date, start_date, end_date)
        async with OuraClient(resolve_pat(pat)) as client:
            return await client.get("daily_resilience", params)

    @mcp.tool()
    @safe_tool
    async def oura_daily_cardiovascular_age(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return Oura estimated cardiovascular age for a date or range.

        Endpoint: /v2/usercollection/daily_cardiovascular_age. Gen 3+ only.

        Returns vascular_age (estimated) vs the user's chronological age.
        May return empty data for devices without the feature.

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.
        """
        params = resolve_date_params(date, start_date, end_date)
        async with OuraClient(resolve_pat(pat)) as client:
            return await client.get("daily_cardiovascular_age", params)

    @mcp.tool()
    @safe_tool
    async def oura_daily_sleep_time(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return Oura recommended bedtime windows for a date or range.

        Endpoint: /v2/usercollection/sleep_time.

        Returns the recommended bedtime start and end timestamps, optimal
        bedtime, and status (recommended / slightly_early / slightly_late /
        not_enough_nights).

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.
        """
        params = resolve_date_params(date, start_date, end_date)
        async with OuraClient(resolve_pat(pat)) as client:
            return await client.get("sleep_time", params)

    # ------------------------------------------------------------------
    # Activity / event endpoints — paginated (step 8)
    # ------------------------------------------------------------------

    @mcp.tool()
    @safe_tool
    async def oura_workouts(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return workout sessions for a date or range.

        Endpoint: /v2/usercollection/workout. Paginated.

        Returns manual and auto-detected workout sessions including
        activity type, start/end timestamps, calories, distance, and more.

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.
        """
        params = resolve_date_params(date, start_date, end_date)
        async with OuraClient(resolve_pat(pat)) as client:
            items = await client.get_all("workout", params)
        return {"data": items}

    @mcp.tool()
    @safe_tool
    async def oura_sessions(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return meditation and breathwork sessions for a date or range.

        Endpoint: /v2/usercollection/session. Paginated.

        Returns guided and unguided meditation, breathwork, napping, and
        relaxation sessions with start/end timestamps and heart rate data.

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.
        """
        params = resolve_date_params(date, start_date, end_date)
        async with OuraClient(resolve_pat(pat)) as client:
            items = await client.get_all("session", params)
        return {"data": items}

    @mcp.tool()
    @safe_tool
    async def oura_tags(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return user-applied tags for a date or range.

        Prefers the /v2/usercollection/enhanced_tag endpoint; automatically
        falls back to /v2/usercollection/tag for older accounts that don't
        have enhanced tags enabled (404 triggers the fallback).

        Returns tag text, timestamp, and tag type_code.
        A _source field in the response indicates which endpoint was used.

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.
        """
        params = resolve_date_params(date, start_date, end_date)
        async with OuraClient(resolve_pat(pat)) as client:
            try:
                items = await client.get_all("enhanced_tag", params)
                return {"data": items, "_source": "enhanced_tag"}
            except OuraAPIError as e:
                if e.status == 404:
                    items = await client.get_all("tag", params)
                    return {"data": items, "_source": "tag"}
                raise

    @mcp.tool()
    @safe_tool
    async def oura_rest_mode_period(
        date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return rest mode periods for a date or range.

        Endpoint: /v2/usercollection/rest_mode_period.

        Rest mode is manually activated by the user when sick or recovering.
        Returns start/end timestamps and episode counts.

        Parameters
        ----------
        date:       Single day YYYY-MM-DD. Defaults to today.
        start_date: Range start YYYY-MM-DD (inclusive). Defaults to today.
        end_date:   Range end YYYY-MM-DD (inclusive). Defaults to today.
        pat:        Override the resolved PAT for this call only.
        """
        params = resolve_date_params(date, start_date, end_date)
        async with OuraClient(resolve_pat(pat)) as client:
            items = await client.get_all("rest_mode_period", params)
        return {"data": items}

    # ------------------------------------------------------------------
    # Heart rate time-series (step 8) — different param signature
    # ------------------------------------------------------------------

    @mcp.tool()
    @safe_tool
    async def oura_heart_rate(
        start_datetime: str | None = None,
        end_datetime: str | None = None,
        format: str = "compact",
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Return time-series heart rate samples between two timestamps.

        Endpoint: /v2/usercollection/heartrate. Paginated.

        Note: this endpoint takes ISO 8601 datetime strings, not plain dates.
        Default range is today 00:00:00 to 23:59:59 local time.

        **Output modes:**
        - format="compact" (default): Returns only a {min,max,avg,samples}
          summary. 5-second samples produce 5000+ values per night; the
          summary is almost always what you want.
        - format="full": Returns the full data array. Use only when you need
          the raw time-series (e.g. to plot HR throughout the night).

        Parameters
        ----------
        start_datetime: ISO 8601 start (e.g. "2026-04-28T00:00:00-07:00").
                        Defaults to today at midnight local time.
        end_datetime:   ISO 8601 end. Defaults to today at 23:59:59 local time.
        format:         "compact" (default) or "full".
        pat:            Override the resolved PAT for this call only.

        Returns (compact)
        -----------------
        {"summary": {"min": 48, "max": 72, "avg": 57.3, "samples": 17280}}

        Returns (full)
        --------------
        {"data": [{"timestamp": "...", "bpm": 55}, ...]}
        """
        today = _date.today().isoformat()
        params = {
            "start_datetime": start_datetime or f"{today}T00:00:00",
            "end_datetime": end_datetime or f"{today}T23:59:59",
        }
        async with OuraClient(resolve_pat(pat)) as client:
            items = await client.get_all("heartrate", params)

        if format == "compact":
            return {"summary": _summarize_items(items)}
        return {"data": items}

    # ------------------------------------------------------------------
    # Device info (step 8) — no date params
    # ------------------------------------------------------------------

    @mcp.tool()
    @safe_tool
    async def oura_ring_configuration(pat: str | None = None) -> dict[str, Any]:
        """Return Oura ring hardware and firmware configuration.

        Endpoint: /v2/usercollection/ring_configuration.

        Returns hardware_type, color, design, firmware_version,
        and hardware_version. No date params.

        Parameters
        ----------
        pat: Override the resolved PAT for this call only.
        """
        async with OuraClient(resolve_pat(pat)) as client:
            return await client.get("ring_configuration")

    # ------------------------------------------------------------------
    # Cache management (step 7)
    # ------------------------------------------------------------------

    @mcp.tool()
    @safe_tool
    async def oura_cache_rebuild(
        start_date: str | None = None,
        end_date: str | None = None,
        pat: str | None = None,
    ) -> dict[str, Any]:
        """Re-fetch a date range from the Oura API and overwrite the local cache.

        Requires OURA_MCP_CACHE_DIR to be set. Fetches sleep sessions,
        daily_sleep, daily_readiness, and daily_spo2 for each day in the
        range and writes one JSON file per day to the cache directory.

        Use this to:
        - Populate the cache for the first time over a historical range.
        - Force-refresh days where Oura has revised scores retroactively.

        Parameters
        ----------
        start_date: Range start YYYY-MM-DD. Defaults to today.
        end_date:   Range end YYYY-MM-DD. Defaults to today.
        pat:        Override the resolved PAT for this call only.

        Returns
        -------
        {"rebuilt": ["YYYY-MM-DD", ...], "count": N}
        """
        from ..cache import CACHE_DIR_ENV, resolve_cache_dir
        from .derived import fetch_summary_range

        cache_dir = resolve_cache_dir()
        if not cache_dir:
            return {
                "error": "cache_not_configured",
                "message": f"Set {CACHE_DIR_ENV} to enable caching.",
            }

        p = resolve_date_params(None, start_date, end_date)
        req_start, req_end = p["start_date"], p["end_date"]

        async with OuraClient(resolve_pat(pat)) as client:
            _, statuses = await fetch_summary_range(
                client, req_start, req_end, force_refresh=True
            )

        return {"rebuilt": sorted(statuses.keys()), "count": len(statuses)}
