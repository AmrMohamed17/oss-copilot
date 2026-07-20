#!/usr/bin/env python3
"""
fetch_issues.py -- Phase 0, Step 0.3: the real data pull.

Differs from probe_repo.py in three ways:
  - 365-day lookback (not 90): rare classes (documentation, question) are thin,
    and history is the only source of more.
  - up to 30 pages (not 10): ~3000 issues/repo ceiling.
  - writes to data/raw/*.jsonl and caches: re-running does not re-hit the API.

Usage:
    python scripts/fetch_issues.py langfuse/langfuse mlflow/mlflow
    python scripts/fetch_issues.py --all
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
API = "https://api.github.com"
LOOKBACK_DAYS = 1095
MAX_PAGES = 100
RAW_DIR = Path("data/raw")

GROUND_TRUTH_REPOS = [
    "langfuse/langfuse",
    "mlflow/mlflow",
    "run-llama/llama_index",
    "vibrantlabsai/ragas",
]
WATCHED_ONLY = ["confident-ai/deepeval"]


def headers() -> dict:
    if not TOKEN:
        sys.exit("ERROR: GITHUB_TOKEN missing. Is .env present?")
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def keep_fields(item: dict) -> dict:
    """Store only what later phases need. Full API objects are ~10x larger and
    most of it (avatar URLs, reaction counts, node_ids) is never read."""
    return {
        "repo": item["repository_url"].removeprefix(f"{API}/repos/"),
        "number": item["number"],
        "title": item["title"],
        "body": item.get("body") or "",
        "labels": [l["name"] for l in item.get("labels", [])],
        "state": item["state"],
        "state_reason": item.get("state_reason"),
        "created_at": item["created_at"],
        "closed_at": item.get("closed_at"),
        "comments": item.get("comments", 0),
        "html_url": item["html_url"],
        "author_type": item.get("user", {}).get("type"),
    }


def fetch(client: httpx.Client, repo: str) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    url = f"{API}/repos/{repo}/issues"
    params = {"state": "all", "per_page": 100, "since": since}
    out: list[dict] = []
    dropped_prs = 0
    dropped_bots = 0

    for page in range(MAX_PAGES):
        r = client.get(url, params=params, headers=headers(), timeout=30)
        if r.status_code in (403, 429):
            print(f"  rate limited after {len(out)} issues -- keeping what we have")
            break
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break

        for item in batch:
            # THE critical filter: /issues returns pull requests too.
            if "pull_request" in item:
                dropped_prs += 1
                continue
            if item.get("user", {}).get("type") == "Bot":
                dropped_bots += 1
                continue
            out.append(keep_fields(item))

        print(f"  page {page + 1}: {len(out)} issues kept", end="\r")
        nxt = r.links.get("next", {}).get("url")
        if not nxt:
            break
        url, params = nxt, None

    print(f"  kept {len(out)} issues | dropped {dropped_prs} PRs, {dropped_bots} bot issues")
    return out


def main() -> None:
    args = sys.argv[1:]
    repos = (GROUND_TRUTH_REPOS + WATCHED_ONLY) if args == ["--all"] else args
    if not repos:
        sys.exit("Usage: python scripts/fetch_issues.py [--all | owner/repo ...]")

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(follow_redirects=True) as client:
        for repo in repos:
            print(f"\n{repo}")
            path = RAW_DIR / f"{repo.replace('/', '__')}.jsonl"
            if path.exists():
                print(f"  cached at {path} -- delete it to refetch")
                continue
            issues = fetch(client, repo)
            with path.open("w") as f:
                for issue in issues:
                    f.write(json.dumps(issue) + "\n")
            print(f"  -> {path}")

        r = client.get(f"{API}/rate_limit", headers=headers(), timeout=30)
        core = r.json()["resources"]["core"]
        print(f"\nrate limit: {core['remaining']}/{core['limit']} remaining")


if __name__ == "__main__":
    main()
