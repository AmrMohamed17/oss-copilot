#!/usr/bin/env python3
"""Step 1 smoke test: prove the watcher can see issues THROUGH the MCP server.

Exercises the real protocol path: spawn server -> list_new_issues -> for the
first issue, get_claim_status. If both return real data, the client works and
Step 2 (the pipeline) can build on it.

    uv run python scripts/smoke_watcher.py
"""
import asyncio
import sys

sys.path.insert(0, "src")
from oss_copilot.watcher.mcp_client import mcp_session, call_tool


async def main():
    async with mcp_session() as s:
        print("session initialized ✓  (MCP server spawned and handshook)")

        res = await call_tool(s, "list_new_issues", {"days": 30})
        if isinstance(res, dict) and res.get("error"):
            print("list_new_issues error:", res["error"]); return
        issues = res.get("issues", [])
        print(f"\nlist_new_issues(days=30): {res.get('count', len(issues))} issues, "
              f"{res.get('pull_requests_excluded', 0)} PRs excluded")
        for i in issues[:5]:
            print(f"  {i['repo']}#{i['number']}  {i['title'][:60]}")

        if issues:
            first = issues[0]
            claim = await call_tool(s, "get_claim_status",
                                    {"repo": first["repo"], "number": first["number"]})
            print(f"\nget_claim_status({first['repo']}#{first['number']}): "
                  f"claimed={claim.get('claimed')}  signals={claim.get('signals')}")
        print("\n✓ MCP client path works end-to-end.")


if __name__ == "__main__":
    asyncio.run(main())