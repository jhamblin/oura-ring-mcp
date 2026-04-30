# Contributing to oura-mcp

## Development setup

```bash
git clone https://github.com/jhamblin/oura-mcp.git
cd oura-mcp
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Running tests

```bash
pytest
```

All tests use `respx` to mock outbound HTTP — no live API calls, no PAT required.

## Test fixtures

`tests/fixtures/sleep_response.json` contains scrubbed sleep data with no real biometric values. If you add a new fixture, ensure:

- No real names, emails, or identifiable information
- Numeric values are plausible but not real (rounded, shifted, or synthetic)
- Timestamps use a clearly fictional date (we use `2026-04-*`)

## Adding a new tool

1. Decide: direct API tool or derived/analytics tool?
   - Direct → add to `src/oura_mcp/tools/direct.py` inside `register(mcp)`
   - Derived → add to `src/oura_mcp/tools/derived.py` inside `register(mcp)`
2. Decorate with `@safe_tool` so errors return structured envelopes instead of raising
3. Use `resolve_date_params` for all date handling (single-date vs range, defaults to today)
4. Write tests in `tests/` before or alongside the implementation
5. Add the tool to the table in `README.md`

## Code style

```bash
ruff check .
ruff format .
```

CI runs both. Pull requests with lint errors will not be merged.

## Commit messages

Use imperative present tense: `Add oura_vo2max tool`, not `Added` or `Adds`.

## PAT safety

Never include a real Personal Access Token in:
- Source code
- Test fixtures
- Commit messages
- Issue or PR descriptions

Tests use `pat="test-token"` throughout. If you accidentally commit a real token, revoke it immediately at [cloud.ouraring.com/personal-access-tokens](https://cloud.ouraring.com/personal-access-tokens) — see [SECURITY.md](./SECURITY.md) for the full incident response procedure.

## Pull requests

- Keep PRs focused: one feature or fix per PR
- Include test coverage for new tools
- Update `README.md` tool reference tables if you add or change a tool's interface
- For large changes, open an issue first to discuss the approach
