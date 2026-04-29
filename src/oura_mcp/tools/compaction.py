"""Compact-mode field stripping for token-efficient output (spec §6).

Sleep periods from the Oura API include several bulky time-series fields that
can blow up LLM context windows:

  heart_rate.items   → 5-second samples, 5000+ values per night
  hrv.items          → 5-minute samples, ~100 values per night
  movement_30_sec    → digit string, ~1000 chars per night
  sleep_phase_30_sec → digit string, ~1000 chars per night

Compact mode (the default) replaces these with small summaries while keeping
sleep_phase_5_min intact (small, needed for hypnogram rendering).

Full mode returns the unmodified Oura response.
"""

from __future__ import annotations

from typing import Any


def _summarize_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute {min, max, avg, samples} from a list of Oura time-series items.

    Each item is expected to have a numeric value under the key "bpm" (heart_rate)
    or "hrv" — we take whichever numeric field is present.
    """
    if not items:
        return {"min": None, "max": None, "avg": None, "samples": 0}

    values: list[float] = []
    for item in items:
        # heart_rate items use "bpm", hrv items use "hrv"
        for key in ("bpm", "hrv"):
            if key in item and item[key] is not None:
                values.append(float(item[key]))
                break

    if not values:
        return {"min": None, "max": None, "avg": None, "samples": len(items)}

    return {
        "min": min(values),
        "max": max(values),
        "avg": round(sum(values) / len(values), 2),
        "samples": len(values),
    }


def compact_sleep_session(session: dict[str, Any]) -> dict[str, Any]:
    """Return a compacted copy of a single sleep session dict.

    Mutations (all non-destructive — operates on a shallow copy):
    - heart_rate.items → heart_rate.summary
    - hrv.items → hrv.summary
    - Drops sleep_phase_30_sec
    - Drops movement_30_sec
    - Keeps sleep_phase_5_min (small, needed for hypnogram)
    """
    out = dict(session)

    # heart_rate
    hr = session.get("heart_rate")
    if isinstance(hr, dict) and "items" in hr:
        out["heart_rate"] = {
            **{k: v for k, v in hr.items() if k != "items"},
            "summary": _summarize_items(hr["items"]),
        }

    # hrv
    hrv = session.get("hrv")
    if isinstance(hrv, dict) and "items" in hrv:
        out["hrv"] = {
            **{k: v for k, v in hrv.items() if k != "items"},
            "summary": _summarize_items(hrv["items"]),
        }

    # Drop bulky strings
    out.pop("sleep_phase_30_sec", None)
    out.pop("movement_30_sec", None)

    return out


def compact_sleep_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply compact_sleep_session to every session in a list."""
    return [compact_sleep_session(s) for s in sessions]
