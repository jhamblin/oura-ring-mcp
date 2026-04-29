# oura-mcp

A Model Context Protocol server exposing the **full** Oura Ring v2 API to LLM agents — including period-level sleep data, time-series HR/HRV, hypnogram, SpO2, and more. Existing community Oura MCPs return only daily contributor scores; this one returns the raw API response.

**Status:** Alpha (v0.1.0.dev0). Implementation in progress against [`oura-mcp-spec.md`](./oura-mcp-spec.md).

## Token safety

The Oura Personal Access Token grants full read access to your biometric history. Treat it like an API key:

- Get one at https://cloud.ouraring.com/personal-access-tokens
- Never commit it. Use the `OURA_PAT` env var or `~/.oura-mcp/config.json`.
- To revoke: cloud.ouraring.com → Personal Access Tokens → delete.

## Quickstart (developer install)

```bash
git clone https://github.com/jhamblin/oura-mcp.git
cd oura-mcp
pip install -e .
export OURA_PAT="your-token"
oura-mcp   # runs as an MCP server on stdio
```

Register with Claude Desktop by adding the snippet from [`examples/claude-config.json`](./examples/claude-config.json) to `claude_desktop_config.json`.

## License

MIT. See [LICENSE](./LICENSE).
