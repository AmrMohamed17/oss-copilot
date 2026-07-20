#!/usr/bin/env python3
"""
probe_repo.py -- evidence for Phase 0, Step 0.1 (repo selection).

Answers, per candidate repo:
  1. Is it ACTIVE?        issues opened in the last 90 days
  2. Is it LABELLED?      % of issues carrying at least one label
  3. Is it TYPE-labelled? % matching common type-label patterns (Gate A)
  4. Is it CONTRIBUTABLE? open 'good first issue' / 'help wanted' count
  5. What vocabulary?     top 25 labels -- the raw material for taxonomy/v1.yaml

Usage:
    python scripts/probe_repo.py vibrantlabsai/ragas
    python scripts/probe_repo.py owner/repo1 owner/repo2 ...
"""

import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
API = "https://api.github.com"
LOOKBACK_DAYS = 90
MAX_PAGES = 10          # 10 pages x 100 = up to 1000 issues. Caps rate-limit burn.
GATE_A_THRESHOLD = 60.0  # % type-labelled required to accept a repo

# Heuristic seed patterns. This is a ROUGH estimate only -- the real mapping is
# built by hand in Step 0.4 (taxonomy/v1.yaml). Repos use wildly different
# vocabularies ("bug" / "type:bug" / "kind/bug" / "C-bug"), so substring matching
# is deliberately loose here. Read the top-25 list before trusting this number.
TYPE_PATTERNS = {
    "bug":           ["bug", "defect", "regression"],
    "feature":       ["feature", "enhancement", "improvement", "proposal"],
    "documentation": ["doc", "documentation"],
    "question":      ["question", "support", "discussion", "help"],
    "maintenance":   ["refactor", "chore", "test", "dependencies", "ci", "build"],
}
CONTRIB_PATTERNS = ["good first issue", "good-first-issue", "help wanted", "help-wanted"]


def headers() -> dict:
    if not TOKEN:
        sys.exit("ERROR: GITHUB_TOKEN not found. Is .env present and filled in?")
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def fetch_issues(client: httpx.Client, repo: str) -> list[dict]:
    """
    Page through recent issues.

    Two details that silently corrupt this dataset if missed:

    1. GitHub's /issues endpoint RETURNS PULL REQUESTS TOO. Every PR appears as an
       issue with an extra 'pull_request' key. Unfiltered, ~40% of your "issues"
       are PRs and every downstream metric is meaningless.

    2. The 'since' parameter filters by UPDATED time, not created time. So we
       over-fetch with 'since', then filter on created_at ourselves. Treating
       'since' as a created-at filter quietly undercounts old-but-active issues.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    issues: list[dict] = []
    url = f"{API}/repos/{repo}/issues"
    params = {"state": "all", "per_page": 100, "since": since}

    for _ in range(MAX_PAGES):
        r = client.get(url, params=params, headers=headers(), timeout=30)
        if r.status_code == 404:
            print(f"  !! {repo}: not found (typo? renamed? moved org?)")
            return []
        if r.status_code == 403:
            print(f"  !! {repo}: rate limited or forbidden.")
            return issues
        r.raise_for_status()

        batch = r.json()
        if not batch:
            break

        for item in batch:
            if "pull_request" in item:          # detail #1 above
                continue
            if item.get("user", {}).get("type") == "Bot":
                continue                        # bot issues aren't human triage signal
            issues.append(item)

        # GitHub paginates via the Link header, not a page count.
        nxt = r.links.get("next", {}).get("url")
        if not nxt:
            break
        url, params = nxt, None

    return issues


def classify_label(name: str) -> str | None:
    low = name.lower()
    for canonical, patterns in TYPE_PATTERNS.items():
        if any(p in low for p in patterns):
            return canonical
    return None


def probe(client: httpx.Client, repo: str) -> None:
    print(f"\n{'=' * 62}\n{repo}\n{'=' * 62}")
    issues = fetch_issues(client, repo)
    if not issues:
        print("  no issues retrieved -- cannot evaluate")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    recent = [
        i for i in issues
        if datetime.fromisoformat(i["created_at"].replace("Z", "+00:00")) >= cutoff
    ]

    label_counter: Counter[str] = Counter()
    any_labelled = 0
    type_labelled = 0
    for i in issues:
        names = [l["name"] for l in i.get("labels", [])]
        label_counter.update(names)
        if names:
            any_labelled += 1
        if any(classify_label(n) for n in names):
            type_labelled += 1

    total = len(issues)
    pct_any = 100 * any_labelled / total
    pct_type = 100 * type_labelled / total

    open_contrib = sum(
        1 for i in issues
        if i["state"] == "open"
        and any(any(p in l["name"].lower() for p in CONTRIB_PATTERNS)
                for l in i.get("labels", []))
    )

    print(f"  issues sampled           : {total}")
    print(f"  opened in last {LOOKBACK_DAYS}d      : {len(recent)}   (activity: need >=20)")
    print(f"  carrying ANY label       : {pct_any:5.1f}%")
    print(f"  carrying a TYPE label    : {pct_type:5.1f}%   (Gate A: need >={GATE_A_THRESHOLD}%)")
    print(f"  open good-first/help-want: {open_contrib}   (contributability)")

    print("\n  top 25 labels -- raw material for taxonomy/v1.yaml:")
    for name, count in label_counter.most_common(25):
        canonical = classify_label(name)
        tag = f"-> {canonical}" if canonical else "   (meta/unmapped)"
        print(f"    {count:5d}  {name[:38]:38s} {tag}")

    active_ok = len(recent) >= 20
    gate_a_ok = pct_type >= GATE_A_THRESHOLD
    verdict = "ACCEPT" if (active_ok and gate_a_ok) else "REJECT / investigate"
    print(f"\n  VERDICT: {verdict}")
    if not active_ok:
        print(f"    - too quiet: {len(recent)} issues in {LOOKBACK_DAYS}d (need >=20)")
    if not gate_a_ok:
        print(f"    - weak labelling: {pct_type:.1f}% type-labelled (need >={GATE_A_THRESHOLD}%)")
        print("      NOTE: check the top-25 list. A custom vocabulary the heuristic")
        print("      missed is fine -- genuinely unlabelled issues are not.")


def main() -> None:
    repos = sys.argv[1:]
    if not repos:
        sys.exit("Usage: python scripts/probe_repo.py owner/repo [owner/repo ...]")

    with httpx.Client(follow_redirects=True) as client:
        for repo in repos:
            probe(client, repo)

        r = client.get(f"{API}/rate_limit", headers=headers(), timeout=30)
        core = r.json()["resources"]["core"]
        print(f"\n\nrate limit: {core['remaining']}/{core['limit']} remaining")


if __name__ == "__main__":
    main()
