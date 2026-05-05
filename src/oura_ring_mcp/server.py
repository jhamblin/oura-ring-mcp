"""MCP server entrypoint. Wires tool packages onto a FastMCP instance and runs stdio."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .tools import derived, direct

mcp = FastMCP("oura-ring-mcp")
direct.register(mcp)
derived.register(mcp)


def main() -> None:
    """Console-script entry point. Runs the MCP server on stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
