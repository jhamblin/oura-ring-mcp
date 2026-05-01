"""Date parameter resolution shared across all date-keyed tools."""

from __future__ import annotations

from datetime import date as _date


def resolve_date_params(
    date: str | None,
    start_date: str | None,
    end_date: str | None,
) -> dict[str, str]:
    """Return ``{"start_date": ..., "end_date": ...}`` for an Oura API call.

    Rules:
    - ``date`` and ``start_date``/``end_date`` are mutually exclusive.
    - If nothing is given, both default to today (local system date — Oura day
      boundaries are user-local, so UTC would give wrong data for callers in non-UTC
      zones after ~5 pm).
    - If only ``start_date`` is given, ``end_date`` defaults to today.
    - If only ``end_date`` is given, ``start_date`` defaults to today.
    """
    if date and (start_date or end_date):
        raise ValueError(
            "Pass either date= for a single day, or start_date=/end_date= for a range — not both."
        )

    if date:
        return {"start_date": date, "end_date": date}

    today = _date.today().isoformat()
    return {
        "start_date": start_date or today,
        "end_date": end_date or today,
    }
