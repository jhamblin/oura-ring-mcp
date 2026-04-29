"""Optional file-based local cache (spec §8).

Enable by setting OURA_MCP_CACHE_DIR=~/.oura-mcp/raw/ in the environment.

One JSON file per day: <cache_dir>/<YYYY-MM-DD>.json

Cache file structure:
{
  "date":             "YYYY-MM-DD",
  "sleep_sessions":   [...],       # /v2/usercollection/sleep (overnight-buffer filtered)
  "daily_sleep":      {...} | null, # /v2/usercollection/daily_sleep
  "daily_readiness":  {...} | null, # /v2/usercollection/daily_readiness
  "daily_spo2":       {...} | null  # /v2/usercollection/daily_spo2
}

Cache-first: past dates are served from cache when a file exists.
Today is always re-fetched (data is incomplete until ~6 h after wake).
Existing files are overwritten on cache writes (Oura may revise scores retro).
"""

from __future__ import annotations

import json
import os
from datetime import date as _date
from pathlib import Path
from typing import Any

CACHE_DIR_ENV = "OURA_MCP_CACHE_DIR"


def resolve_cache_dir() -> Path | None:
    """Return the cache directory from OURA_MCP_CACHE_DIR env var, or None if unset."""
    val = os.environ.get(CACHE_DIR_ENV)
    if not val:
        return None
    return Path(val).expanduser()


def is_today(date_str: str) -> bool:
    """Return True if date_str is today's local date (always re-fetch today)."""
    return date_str == _date.today().isoformat()


def cache_read(cache_dir: Path, date_str: str) -> dict[str, Any] | None:
    """Return cached day data, or None on miss / today / read error."""
    if is_today(date_str):
        return None
    path = cache_dir / f"{date_str}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def cache_write(cache_dir: Path, date_str: str, data: dict[str, Any]) -> None:
    """Write day data to <cache_dir>/<date_str>.json, creating dirs as needed."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{date_str}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
