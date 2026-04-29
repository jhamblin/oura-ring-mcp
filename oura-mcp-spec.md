# oura-mcp — Specification

A Model Context Protocol server that exposes the **full** Oura Ring v2 API to LLM agents, with first-class support for sleep period data, time-series signals, and date-range queries.

**Status:** Specification. Not yet implemented.
**Target:** Open-source release on GitHub + PyPI.
**License:** MIT.

---

## 1. Motivation

The existing community Oura MCP servers we tested return only **daily contributor scores** (e.g. `deep_sleep: 11`, `efficiency: 88`) — opaque 0–100 numbers from Oura's scoring algorithm. They omit the underlying period data: actual minutes of deep/REM/light sleep, sleep stage timeline, restless periods, breathing rate, SpO2, time-series HR/HRV, etc.

For any non-trivial analysis (correlation studies, intervention testing, hypnogram visualization, percentile tracking), the contributor scores are useless. The agent needs the raw API response.

This MCP exists to fix that gap. It is a **fidelity-first** wrapper: the goal is to expose the full Oura v2 API surface with structured, parseable data, plus a small set of optional aggregation tools that operate on the raw data.

A reference implementation in Python (`oura_fetch.py`, ~510 LOC) already exists in the project that motivated this spec. It demonstrates the API access patterns, the overnight-sleep filtering detail, and the hypnogram rendering. That script should be consulted during implementation.

---

## 2. Goals & Non-Goals

### Goals
- Expose every read-only Oura v2 `usercollection` endpoint as an MCP tool.
- Return structured data (parsed JSON), not pre-summarized scores.
- Support both single-date and date-range queries on every applicable tool.
- Provide a small set of derived tools (hypnogram, percentiles, rolling trends) that operate on the raw data.
- Optional local cache: write raw API responses to disk so analyses are reproducible and offline-capable.
- Minimal config: PAT via env var or one-line config file. No interactive setup.
- Token-efficient: support a `compact` output mode that strips bulky time-series arrays when the caller only needs aggregates.

### Non-Goals
- **No write operations.** This MCP is read-only. Tags and workouts may be writable via Oura's API; we don't expose those.
- **No wiki-specific formatting.** The reference script renders markdown tables for a specific Obsidian wiki — that logic stays in the consumer, not the MCP.
- **No credential management UI.** PAT comes from env or file; users get their own from cloud.ouraring.com.
- **No re-authentication / OAuth.** Personal Access Tokens only. OAuth is appropriate for multi-user services and out of scope here.
- **No rate-limit retry logic beyond simple backoff.** The Oura API is generous (5000 req/day); aggressive retry strategy is unnecessary and risks lockout.

---

## 3. Architecture

```
┌─────────────────┐     stdio       ┌──────────────┐    HTTPS     ┌─────────────┐
│  MCP client     │ ◄─────────────► │  oura-mcp    │ ◄──────────► │  Oura API   │
│  (Claude, etc)  │   JSON-RPC      │   server     │   v2 REST    │             │
└─────────────────┘                  └──────┬───────┘              └─────────────┘
                                            │
                                            │ optional
                                            ▼
                                    ┌───────────────┐
                                    │ local cache   │
                                    │ ~/.oura-mcp/  │
                                    │ raw/YYYY-MM-DD│
                                    │   .json       │
                                    └───────────────┘
```

- **Transport:** stdio (the MCP standard for local servers). Optionally HTTP for hosted use.
- **Language:** Python 3.10+. Use the official `mcp` SDK (`pip install mcp`).
- **HTTP client:** `httpx` (async) for parallel multi-endpoint fetches when a single tool call requires more than one Oura endpoint.
- **State:** stateless server. Optional file-based cache.

---

## 4. Authentication

```
OURA_PAT=<personal-access-token>
```

Resolution order:
1. `OURA_PAT` environment variable.
2. `~/.oura-mcp/config.json` → `{"pat": "..."}`.
3. Per-call `pat` argument (allows multi-account scenarios; not recommended for normal use).

If unresolved, every tool returns a structured error directing the user to https://cloud.ouraring.com/personal-access-tokens.

### 4.1 Credential safety (mandatory)

A leaked Oura PAT grants full read access to someone's biometric history. Treat this with the same care as an API key.

- **No PATs anywhere in the source tree.** No defaults, no examples, no placeholders that look like real tokens.
- **`.gitignore` must include from day one:**
  ```
  .env
  .env.*
  config.json
  **/oura-mcp/config.json
  ~/.oura-mcp/
  tests/fixtures/*.real.json
  *.pat
  ```
- **Test fixtures** (`tests/fixtures/`) must be **scrubbed** before commit. Use a fixture-capture helper that replaces real tokens with `"REDACTED"` and randomizes any user-identifying fields (`user_id`, names). Document this in `CONTRIBUTING.md`.
- **Logging:** never log the PAT, never log full Authorization headers, never log raw URLs that might include credentials in query strings (Oura's PAT is header-only, but enforce the rule generically). The httpx client should install a redacting log filter.
- **Errors:** authentication failures return `"PAT not configured"` or `"PAT rejected by Oura"` — never echo the offending value.
- **Pre-commit hook (recommended in `CONTRIBUTING.md`):** `gitleaks` or `detect-secrets`, scoped to catch any token-shaped string. Add a CI job that runs the same scan on every PR.
- **README** must include a one-paragraph "Token safety" callout near the install instructions: where to get a PAT, why it's sensitive, how to revoke one (cloud.ouraring.com → Personal Access Tokens → delete).
- **Example config files** in the repo must use the literal string `YOUR_PAT_HERE` and include a comment warning not to commit a populated copy.

If a PAT is ever accidentally committed, the response is: revoke the token at cloud.ouraring.com immediately, then `git filter-repo` (not just delete-and-recommit — the token is in history forever otherwise), then force-push. Document this incident-response in `SECURITY.md`.

---

## 5. Tool Surface

### Naming convention
- Direct API mirrors: `oura_<resource>` (e.g. `oura_sleep`, `oura_daily_sleep`).
- Derived/aggregation tools: `oura_<verb>_<resource>` (e.g. `oura_render_hypnogram`, `oura_percentiles`).

### Common parameters
- `date: str` — `YYYY-MM-DD`. Defaults to today.
- `start_date: str` and `end_date: str` — for range queries. Inclusive on both ends.
- `format: "full" | "compact"` — defaults to `"compact"` for tools that return bulky time-series data; `"full"` returns the unmodified Oura response.

### 5.1 Direct API tools

| Tool | Oura endpoint | Returns | Notes |
|---|---|---|---|
| `oura_sleep` | `/v2/usercollection/sleep` | All sleep periods (long_sleep + naps) overlapping the date range. **This is the critical missing piece in existing MCPs.** Each period includes `deep_sleep_duration`, `rem_sleep_duration`, `light_sleep_duration`, `awake_time`, `latency`, `efficiency`, `restless_periods`, `average_breath`, `average_hrv`, `lowest_heart_rate`, `sleep_phase_5_min`, `sleep_phase_30_sec`, `movement_30_sec`, time-series `heart_rate`, time-series `hrv`. | Implement the 1-day buffer trick (see §7) so that overnight sleeps are not missed at range boundaries. |
| `oura_daily_sleep` | `/v2/usercollection/daily_sleep` | Daily sleep score + contributors. | Cheap; useful for quick lookups. |
| `oura_daily_readiness` | `/v2/usercollection/daily_readiness` | Daily readiness score + contributors + temperature_deviation. | |
| `oura_daily_activity` | `/v2/usercollection/daily_activity` | Steps, calories, MET minutes, activity contributors. | |
| `oura_daily_spo2` | `/v2/usercollection/daily_spo2` | Average SpO2 percentage and breathing disturbance index. | Sometimes empty for older devices. |
| `oura_daily_stress` | `/v2/usercollection/daily_stress` | Stress high/medium/low/recovery durations. | Gen 3+ only. |
| `oura_daily_resilience` | `/v2/usercollection/daily_resilience` | Resilience level, contributors. | Gen 3+ only. |
| `oura_daily_cardiovascular_age` | `/v2/usercollection/daily_cardiovascular_age` | Estimated CV age vs chronological. | Gen 3+ only. |
| `oura_daily_sleep_time` | `/v2/usercollection/sleep_time` | Recommended bedtime range. | |
| `oura_workouts` | `/v2/usercollection/workout` | Workout sessions (manual or auto-detected). | |
| `oura_sessions` | `/v2/usercollection/session` | Meditation/breathwork sessions. | |
| `oura_tags` | `/v2/usercollection/tag` (deprecated) and `/enhanced_tag` | User-applied tags. | Prefer `enhanced_tag`; fall back to `tag` for older accounts. |
| `oura_heart_rate` | `/v2/usercollection/heartrate` | Time-series HR samples between two timestamps. | Bulky; default to `compact` mode (downsample to 5-min bins). |
| `oura_rest_mode_period` | `/v2/usercollection/rest_mode_period` | Rest mode periods. | |
| `oura_ring_configuration` | `/v2/usercollection/ring_configuration` | Hardware/firmware info. | |
| `oura_personal_info` | `/v2/usercollection/personal_info` | Sex, age, height, weight (user-entered). | One call, no date params. |

### 5.2 Derived tools

| Tool | Inputs | Returns | Notes |
|---|---|---|---|
| `oura_render_hypnogram` | `date`, optional `chars_per_5min=1` | ASCII string with `█` deep, `░` light, `▒` REM, `·` awake — one char per 5 minutes. | Driven by `sleep_phase_5_min` string. Mirrors the reference implementation. |
| `oura_percentiles` | `metric` (e.g. `deep_sleep_duration`), `start_date`, `end_date`, `percentiles=[50,75,95]` | Structured percentile report including count, min, max, requested percentiles. | Operates on `oura_sleep` results internally. |
| `oura_rolling_average` | `metric`, `start_date`, `end_date`, `window=7` | Array of `{date, value, rolling_avg}`. | |
| `oura_summary_table` | `start_date`, `end_date` | Compact JSON array of `{date, deep_min, rem_min, light_min, awake_min, efficiency, hrv, rhr, sleep_score, readiness_score}` — one row per night. | Highest-value tool for analysis workflows. ~200 tokens per night. |

The derived tools must be implementable as thin wrappers over the direct API tools — no business logic that diverges from raw Oura semantics.

---

## 6. Output Strategy

Bulky fields balloon LLM context fast. Specifically:

- `heart_rate.items` → 5-second samples, 5000+ values per night
- `hrv.items` → 5-minute samples, ~100 values per night
- `movement_30_sec` → string of digits, ~1000 chars per night
- `sleep_phase_30_sec` → string, ~1000 chars per night

### `compact` mode (default)
- Drop `heart_rate.items` (replace with `heart_rate.summary = {min, max, avg, samples}`).
- Drop `hrv.items` (replace with `hrv.summary = {min, max, avg, samples}`).
- Keep `sleep_phase_5_min` (small, useful for hypnogram rendering).
- Drop `sleep_phase_30_sec` and `movement_30_sec`.

### `full` mode
- Return unmodified Oura response. Caller is responsible for context budget.

Document this clearly in each tool's description so the agent knows what it's getting.

---

## 7. Critical Implementation Detail: Overnight Sleep Filtering

The Oura `/sleep` endpoint filters by `bedtime_start` date, **not** by the logical `day` field. A sleep starting at 11:30pm on Apr 12 has `bedtime_start = 2026-04-12T23:30:00` but `day = 2026-04-13` (the wake date — Oura's convention).

If a caller asks for sleep on Apr 13, naive filtering misses this session.

**Fix** (from reference implementation):
1. Fetch sleep with `start_date = requested_start - 1 day` and `end_date = requested_end + 1 day`.
2. Filter results in memory to only those where `s["day"]` falls within the originally requested range.

This buffer applies only to the `/sleep` endpoint. All other endpoints filter by `day` directly and don't need it.

---

## 8. Local Cache (Optional but Recommended)

Set `OURA_MCP_CACHE_DIR=~/.oura-mcp/raw/` (or pass `--cache-dir` at startup) to enable.

- One JSON file per day: `<cache_dir>/<YYYY-MM-DD>.json`
- Cached structure: `{"date": ..., "sleep_sessions": [...], "daily_sleep": {...}, "daily_readiness": {...}, "daily_spo2": {...}}`
- Cache-first read for any past date; today's date always re-fetched (data is incomplete until ~6 hours after wake).
- A `cache_status` field in every response indicates `hit`, `miss`, or `disabled`.
- A `oura_cache_rebuild` tool re-fetches a date range and overwrites the cache.

This makes analyses reproducible: an LLM agent can replay the same query against the cache without burning API calls or being subject to data drift if Oura recomputes scores.

---

## 9. Project Layout

```
oura-mcp/
├── README.md
├── LICENSE                       # MIT
├── pyproject.toml
├── src/oura_mcp/
│   ├── __init__.py
│   ├── server.py                 # MCP entrypoint; wires tools to handlers
│   ├── client.py                 # httpx-based Oura API client
│   ├── auth.py                   # PAT resolution
│   ├── cache.py                  # Optional local cache
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── direct.py             # Direct API mirror tools
│   │   ├── derived.py            # Hypnogram, percentiles, rolling avg
│   │   └── compaction.py         # compact-mode field stripping
│   └── schemas.py                # Pydantic models for params + responses
├── tests/
│   ├── test_client.py
│   ├── test_compaction.py
│   ├── test_overnight_filter.py  # Regression for the §7 bug
│   ├── test_cache.py
│   └── fixtures/
│       └── sleep_response.json   # Captured real responses for replay
└── examples/
    ├── claude-config.json        # MCP server registration snippet
    └── analysis-notebook.ipynb   # Demo: fetch + analyze a month of sleep
```

---

## 10. Implementation Order

1. **Bootstrap.** `pyproject.toml`, MCP server skeleton, `oura_personal_info` tool. Verify end-to-end MCP connectivity with Claude Desktop.
2. **Auth + client.** PAT resolution, httpx client, structured error responses.
3. **Direct tools — daily endpoints.** `oura_daily_sleep`, `oura_daily_readiness`, `oura_daily_activity`, `oura_daily_spo2`. Easy; same shape.
4. **Direct tools — sleep periods.** `oura_sleep` with overnight buffer logic. **Write the regression test before the code** (`tests/test_overnight_filter.py`).
5. **Compact mode.** Field-stripping logic + `format` param threaded through. Test with captured fixtures.
6. **Derived tools.** Hypnogram, percentiles, rolling average, summary table.
7. **Cache.** File-based read-through cache. Cache-status field in every response.
8. **Remaining direct tools.** Workouts, sessions, tags, heart_rate, stress, resilience, etc.
9. **Docs + examples.** README walkthrough, Claude Desktop config snippet, analysis notebook.
10. **Release.** Publish to PyPI as `oura-mcp`. Tag v0.1.0.

Each step should ship as a separate commit with tests. Steps 1–4 are the MVP — usable for the original sleep-analysis use case.

---

## 11. Testing Approach

- **Unit tests:** parameter validation, compaction logic, overnight buffer math.
- **Replay tests:** captured Oura responses in `tests/fixtures/`. Never hit the live API in CI.
- **Live smoke test:** a single optional `pytest -m live` that exercises one read against the real API. Requires `OURA_PAT` in env. Skipped by default.
- **Coverage target:** 90%+ on `client.py` and `tools/`. Lower OK on `server.py` (mostly glue).

---

## 12. Open Source Plan

- **Repo:** `github.com/jhamblin/oura-mcp`
- **License:** MIT
- **Package:** PyPI `oura-mcp`
- **README sections:**
  1. What it is + comparison table vs existing MCPs (the "why this exists" angle from §1)
  2. Quickstart: `pip install oura-mcp` → set PAT → register with Claude Desktop
  3. Tool reference (auto-generated from docstrings if possible)
  4. Output modes explained with examples
  5. Cache behavior
  6. Contributing guide
- **Discoverability:** submit to `awesome-mcp-servers`. Post in r/ouraring, the Oura developer forum, and the Anthropic MCP Discord.
- **Versioning:** semver. Pin to Oura API v2; bump major if Oura ships v3.

---

## 13. Reference Implementation Notes

Until this MCP exists, the reference behavior is `tools/oura_fetch.py` in the project that motivated this spec. Specifically:

- API endpoints: `sleep`, `daily_sleep`, `daily_readiness`, `daily_spo2` (see `fetch_range`)
- Overnight buffer trick: see `fetch_range` docstring
- Hypnogram rendering: see `render_hypnogram`
- PAT resolution: see `load_pat`
- Raw cache layout: see `save_raw`

The MCP should reproduce these behaviors with no semantic change — just exposed via JSON-RPC tool calls instead of a CLI.

---

## 14. Open Questions

1. **TypeScript port?** Python is fine for v0.1; a TS port would broaden the contributor base. Defer.
2. **Webhook support?** Oura supports webhooks for new data. Out of scope for v0.1 (would require HTTP transport + persistent state).
3. **Multi-account?** Per-call PAT param allows it, but no first-class support. Add if real demand emerges.
4. **`enhanced_tag` vs `tag`?** Both exist; `enhanced_tag` is preferred. Implement both; expose `oura_tags` that auto-selects.

---

## 15. Acceptance Criteria for v0.1

- [ ] All §5.1 tools implemented and tested.
- [ ] Hypnogram + summary_table derived tools implemented.
- [ ] Compact mode default; full mode opt-in.
- [ ] Overnight buffer bug has a regression test that fails without the fix.
- [ ] PAT auth works from env and config file.
- [ ] All §4.1 credential-safety items in place: `.gitignore`, scrubbed fixtures, redacting log filter, no PATs in source, pre-commit secret scan, `SECURITY.md`, README token-safety callout.
- [ ] Optional local cache with cache-status reporting.
- [ ] README + one example notebook.
- [ ] Published to PyPI.
- [ ] Reference user (the spec author) can replicate `oura_fetch.py`'s output entirely through MCP tool calls.
