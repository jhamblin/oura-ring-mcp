"""Date parameter resolution shared across all date-keyed tools."""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime


def _parse_iso_date(value: str, field_name: str) -> None:
    """Validate that a value is a YYYY-MM-DD date string."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD; got {value!r}") from exc


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
        _parse_iso_date(date, "date")
        return {"start_date": date, "end_date": date}

    if start_date:
        _parse_iso_date(start_date, "start_date")
    if end_date:
        _parse_iso_date(end_date, "end_date")

    today = _date.today().isoformat()
    resolved = {"start_date": start_date or today, "end_date": end_date or today}
    if resolved["start_date"] > resolved["end_date"]:
        raise ValueError("start_date must be on or before end_date")
    return resolved
