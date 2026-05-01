# oura-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server that exposes the **full** Oura Ring v2 API to LLM agents — including period-level sleep data, time-series HR/HRV, hypnogram rendering, SpO2, and derived analytics tools.

## Why this exists

Existing community Oura MCP servers return only **daily contributor scores** — opaque 0–100 numbers from Oura's algorithm (`deep_sleep: 11`, `efficiency: 88`). They omit the underlying period data: actual minutes of deep/REM/light sleep, sleep stage timeline, restless periods, breathing rate, SpO2, time-series heart rate and HRV.

For any non-trivial analysis — correlation studies, intervention tracking, hypnogram visualisation, percentile comparisons — the contributor scores are useless. `oura-mcp` fixes that gap.

| Feature | Existing MCPs | oura-mcp |
|---|---|---|
| Daily sleep score | ✓ | ✓ |
| Actual deep/REM/light minutes | ✗ | ✓ |
| Hypnogram (sleep stage timeline) | ✗ | ✓ |
| Time-series HRV / heart rate | ✗ | ✓ |
| SpO2, breathing rate, restless periods | ✗ | ✓ |
| Date-range queries | partial | ✓ all tools |
| Percentile & trend analytics | ✗ | ✓ |
| Local cache (reproducible analyses) | ✗ | ✓ |
| Compact mode (token-efficient) | ✗ | ✓ |

---

## Token safety

> **Your Oura PAT grants full read access to your biometric history. Treat it like an API key.**

- Get a token at https://cloud.ouraring.com/personal-access-tokens
- Set it via the `OURA_PAT` environment variable or `~/.oura-mcp/config.json` — never in source code
- To revoke: cloud.ouraring.com → Personal Access Tokens → delete

If a token is accidentally committed: revoke it immediately at cloud.ouraring.com, then use `git filter-repo` to purge it from history (a simple delete-and-recommit leaves it in the log forever). See [SECURITY.md](./SECURITY.md).

---

## Quickstart

**1. Install**

```bash
pip install oura-ring-mcp
```

Or for a developer install from source:

```bash
git clone https://github.com/jhamblin/oura-mcp.git
cd oura-mcp
pip install -e .
```

**2. Set your PAT**

```bash
# Option A — environment variable (recommended for Claude Desktop)
export OURA_PAT="your-token-here"

# Option B — config file
mkdir -p ~/.oura-mcp
echo '{"pat": "your-token-here"}' > ~/.oura-mcp/config.json
```

**3. Register with Claude Desktop**

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "oura": {
      "command": "oura-ring-mcp",
      "env": {
        "OURA_PAT": "your-token-here"
      }
    }
  }
}
```

Restart Claude Desktop. Ask it to call `oura_personal_info` to verify connectivity.

**4. (Optional) Enable local cache**

```bash
export OURA_MCP_CACHE_DIR=~/.oura-mcp/raw
```

With the cache enabled, past dates are served from disk — analyses are reproducible and don't burn API calls on repeat queries.

---

## Tool reference

### Direct API tools

| Tool | Oura endpoint | Notes |
|---|---|---|
| `oura_personal_info` | `/personal_info` | Profile (sex, age, height, weight). Connectivity check. |
| `oura_sleep` | `/sleep` | **Primary tool.** Period-level data: deep/REM/light minutes, hypnogram, HRV, HR, SpO2, restless periods. Overnight buffer applied automatically. |
| `oura_daily_sleep` | `/daily_sleep` | Daily sleep score + contributors. |
| `oura_daily_readiness` | `/daily_readiness` | Readiness score + contributors + temperature deviation. |
| `oura_daily_activity` | `/daily_activity` | Steps, calories, MET minutes, activity score. |
| `oura_daily_spo2` | `/daily_spo2` | Average SpO2 + breathing disturbance index. Gen 3 / data-dependent. |
| `oura_daily_stress` | `/daily_stress` | Stress/recovery duration breakdown. Gen 3+. |
| `oura_daily_resilience` | `/daily_resilience` | Resilience level + contributors. Gen 3+. |
| `oura_daily_cardiovascular_age` | `/daily_cardiovascular_age` | Estimated vascular age. Gen 3+. |
| `oura_daily_sleep_time` | `/sleep_time` | Recommended bedtime window + status. |
| `oura_workouts` | `/workout` | Workout sessions (manual + auto-detected). |
| `oura_sessions` | `/session` | Meditation / breathwork sessions. |
| `oura_tags` | `/enhanced_tag` → `/tag` | User tags. Auto-selects enhanced_tag; falls back on 404. |
| `oura_heart_rate` | `/heartrate` | Time-series HR. Takes ISO datetimes. Compact by default. |
| `oura_rest_mode_period` | `/rest_mode_period` | Rest mode (sick / recovery) periods. |
| `oura_ring_configuration` | `/ring_configuration` | Hardware / firmware info. |

### Derived / analytics tools

| Tool | Inputs | Returns |
|---|---|---|
| `oura_render_hypnogram` | `date` | ASCII sleep stage timeline: `█=deep ░=light ▒=REM ·=awake` (5 min/char) |
| `oura_percentiles` | `metric`, date range, `percentiles=[50,75,95]` | P50/P75/P95 (configurable) for any sleep session field |
| `oura_rolling_average` | `metric`, date range, `window=7` | `[{date, value, rolling_avg}]` per day |
| `oura_summary_table` | date range | Compact per-night rows: `{date, deep_min, rem_min, light_min, awake_min, efficiency, hrv, rhr, sleep_score, readiness_score, cache_status}` |
| `oura_cache_rebuild` | date range | Force-refresh cache from API for a date range |

### Common parameters

All date-keyed tools accept:
- `date`: single day `YYYY-MM-DD` (defaults to today)
- `start_date` / `end_date`: inclusive range (each defaults to today)
- `pat`: per-call PAT override (for multi-account use)

`date` and `start_date`/`end_date` are mutually exclusive.

---

## Output modes

Most data-heavy tools support a `format` parameter:

### `compact` (default)

Strips bulky time-series arrays and replaces them with summaries:

- `heart_rate.items` (5-sec samples, 5000+/night) → `heart_rate.summary = {min, max, avg, samples}`
- `hrv.items` (~100 values/night) → `hrv.summary = {min, max, avg, samples}`
- `sleep_phase_30_sec`, `movement_30_sec` dropped
- `sleep_phase_5_min` kept (small; used for hypnogram rendering)

Typical `oura_sleep` response in compact mode: ~2–3 KB per night.

### `full`

Returns the unmodified Oura API response. Use when you need raw time-series for plotting or custom analysis. Caller is responsible for context budget.

---

## Cache behaviour

Set `OURA_MCP_CACHE_DIR` to enable the local cache.

- One JSON file per day: `<cache_dir>/<YYYY-MM-DD>.json`
- **Cache-first** for past dates: if the file exists, the API is not called
- **Today always re-fetched**: data is incomplete until ~6 hours after wake
- **`cache_status`** field on every `oura_summary_table` row: `"hit"`, `"miss"`, or `"disabled"`
- **`oura_cache_rebuild`**: force-refresh a date range (useful for historical backfills or after Oura revises scores retroactively)

Cache files match the structure of `oura_fetch.py`'s `raw/oura/` layout, so existing raw data from that script is compatible.

---

## Implementation notes

### Overnight sleep buffer

The Oura `/sleep` endpoint filters by `bedtime_start`, not by the logical `day` field. A sleep starting at 11:30 pm on Apr 12 has `day = 2026-04-13` (the wake date). `oura_sleep` automatically expands the fetch range by ±1 day and filters results in memory by `day`, so overnight sleeps are never missed. This is regression-tested in `tests/test_overnight_filter.py`.

### Pagination

Oura paginates `/sleep`, `/heartrate`, `/workout`, `/session`, and others via `next_token`. All tools that use these endpoints call `get_all()`, which follows `next_token` until exhausted.

---

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## Security

See [SECURITY.md](./SECURITY.md).

## License

MIT. See [LICENSE](./LICENSE).
