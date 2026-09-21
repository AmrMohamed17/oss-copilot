"""MCP client — connects the watcher to the published oss-issues-mcp server.

This is the point of having built the server: the agent consumes it over the
MCP protocol (stdio), not by importing its internals. The server is spawned as
a subprocess; GITHUB_TOKEN is passed through its environment.

Everything async is hidden behind one context manager + call_tool, so the
pipeline code stays readable.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# The console entry point installed by the oss-issues-mcp package.
# Override with OSS_MCP_CMD if you run the server a different way.
SERVER_CMD = os.getenv("OSS_MCP_CMD", "oss-issues-mcp")


@asynccontextmanager
async def mcp_session():
    """Open one session, reuse it for many tool calls (cheaper than per-call)."""
    if not os.getenv("GITHUB_TOKEN"):
        raise RuntimeError("GITHUB_TOKEN not set — the MCP server needs it.")
    params = StdioServerParameters(command=SERVER_CMD, args=[], env={**os.environ})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def _parse(result) -> dict | list:
    """Tool results arrive as content blocks; take the first text block as JSON."""
    for block in result.content:
        if getattr(block, "type", None) == "text":
            try:
                return json.loads(block.text)
            except json.JSONDecodeError:
                return {"error": f"non-JSON tool output: {block.text[:200]}"}
    return {"error": "no text content in tool result"}


async def call_tool(session, name: str, arguments: dict) -> dict | list:
    return _parse(await session.call_tool(name, arguments))