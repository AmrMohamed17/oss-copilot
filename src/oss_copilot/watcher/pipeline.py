"""The daily pipeline: MCP fetch -> readiness judge -> claim check -> gates.

Sequential by design (a few dozen issues/day) with light rate-limiting. The
sync readiness judge is called inside the async loop — fine at this scale.
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, "src")
from oss_copilot.readiness.judge import judge_issue
from oss_copilot.watcher.mcp_client import mcp_session, call_tool
from oss_copilot.watcher import gates, state


async def build_digest(days: int = 14, max_age_days: int = 120,
                       limit: int | None = None, dry_run: bool = False) -> tuple[list, dict]:
    conn = state.get_conn()
    state.init_schema(conn)

    surfaced, filtered, scanned = [], 0, 0
    async with mcp_session() as s:
        res = await call_tool(s, "list_new_issues", {"days": days})
        issues = res.get("issues", []) if isinstance(res, dict) else []
        if limit:
            issues = issues[:limit]

        for issue in issues:
            repo, num = issue["repo"], issue["number"]
            st = state.get_state(conn, repo, num)
            if st and st[2] is not None:      # surfaced_at set -> already shown
                continue
            scanned += 1

            # readiness: cached, else judge (needs the normalized body)
            if st and st[0]:
                verdict, reason = st[0], st[1]
            else:
                norm = await call_tool(s, "get_actionable_issue",
                                       {"repo": repo, "number": num})
                if isinstance(norm, dict) and norm.get("error"):
                    filtered += 1; continue
                j = judge_issue(norm["title"], norm["body"])
                if j.get("error"):
                    filtered += 1; continue
                verdict, reason = j["verdict"], j.get("reason", "")
                if not dry_run:
                    state.record_readiness(conn, repo, num, verdict, reason)
                time.sleep(0.3)

            # claim status: always fresh
            claim = await call_tool(s, "get_claim_status", {"repo": repo, "number": num})
            if isinstance(claim, dict) and claim.get("error"):
                claim = {"claimed": False}

            gr = gates.evaluate(issue, claim, verdict, max_age_days)
            if not gr.passed:
                filtered += 1
                continue

            surfaced.append({**issue, "reason": reason, "signals": gr.signals})
            if not dry_run:
                state.mark_surfaced(conn, repo, num)

    conn.close()
    stats = {"scanned": scanned, "surfaced": len(surfaced), "filtered": filtered}
    return surfaced, stats