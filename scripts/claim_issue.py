#!/usr/bin/env python3
"""Draft and post a claim comment — with a hard human-approval gate.

    uv run python scripts/claim_issue.py owner/repo#123            # conservative draft
    uv run python scripts/claim_issue.py owner/repo#123 --fix      # names a fix (verify first!)
    uv run python scripts/claim_issue.py owner/repo#123 --dry-run  # never posts

Posting requires GITHUB_WRITE_TOKEN in the environment AND the MCP server at
v0.2.0 (with post_issue_comment). Nothing posts without an explicit 'p'.
"""
import argparse
import asyncio
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, "src")
from oss_copilot.watcher.mcp_client import mcp_session, call_tool
from oss_copilot.claim.draft import draft_comment


def parse_ref(ref: str):
    m = re.match(r"^([\w.-]+/[\w.-]+)#(\d+)$", ref.strip())
    if not m:
        sys.exit("Usage: claim_issue.py owner/repo#123 [--fix] [--dry-run]")
    return m.group(1), int(m.group(2))


def edit_text(initial: str) -> str:
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as f:
        f.write(initial); path = f.name
    subprocess.call([os.getenv("EDITOR", "nano"), path])
    return open(path).read().strip()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("--fix", action="store_true", help="name a specific fix (verify it first)")
    ap.add_argument("--dry-run", action="store_true", help="never post")
    a = ap.parse_args()
    repo, num = parse_ref(a.ref)

    if not a.dry_run and not os.getenv("GITHUB_WRITE_TOKEN"):
        print("Note: GITHUB_WRITE_TOKEN not set — running as dry-run.\n")
        a.dry_run = True

    async with mcp_session() as s:
        issue = await call_tool(s, "get_actionable_issue", {"repo": repo, "number": num})
        if isinstance(issue, dict) and issue.get("error"):
            sys.exit(f"fetch failed: {issue['error']}")

        claim = await call_tool(s, "get_claim_status", {"repo": repo, "number": num})
        if claim.get("claimed"):
            print(f"⚠️  {repo}#{num} appears already claimed "
                  f"(signals: {claim.get('signals')}). Aborting."); return

        print(f"\n{'='*70}\n{repo}#{num}\n{issue['title']}\n{'='*70}")
        print(issue["body"][:900])
        print(f"\n→ {issue['url']}")
        if a.fix:
            print("\n⚠️  --fix mode: the draft may name a specific fix. VERIFY it against "
                  "the real code before posting — it's your credibility on the line.")

        draft = draft_comment(issue["title"], issue["body"], name_fix=a.fix)
        if draft.get("error"):
            sys.exit(f"draft failed: {draft['error']}")
        comment = draft["comment"]

        while True:
            print(f"\n{'-'*70}\nDRAFT:\n{'-'*70}\n{comment}\n{'-'*70}")
            if a.dry_run:
                print("[dry-run] not posting.")
            c = input("[p]ost  [e]dit  [c]ancel > ").strip().lower()
            if c == "c":
                print("Cancelled. Nothing posted."); return
            if c == "e":
                comment = edit_text(comment); continue
            if c == "p":
                break

        if a.dry_run:
            print(f"\n[DRY RUN] Would post to {issue['url']}:\n\n{comment}")
            return

        # final confirmation before an irreversible public action
        if input(f"\nPost this to {issue['url']} for real? type 'yes' > ").strip() != "yes":
            print("Not posted."); return
        res = await call_tool(s, "post_issue_comment",
                              {"repo": repo, "number": num, "body": comment})
        if res.get("posted"):
            print(f"\n✓ Posted: {res['url']}")
        else:
            print(f"\n✗ Post failed: {res.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())