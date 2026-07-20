#!/usr/bin/env python3
"""
build_calibration_set.py -- Phase 0: the reproduction-readiness answer key.

WHAT THIS IS FOR
  The readiness judge is an LLM with a rubric. Nothing is trained. This set
  measures whether its judgements AGREE WITH HUMAN MAINTAINERS.

CLASSES
  positive ("needs info")  -- a maintainer applied a needs-info label.
                              Direct human judgement: not actionable as filed.
  negative ("actionable")  -- closed as COMPLETED and never carried a
                              needs-info label. Someone worked it to
                              resolution, so it was actionable as filed.

  Why not "any issue without the label" as negative? Because absence of the
  label usually means nobody triaged it. That would train the judge to detect
  MAINTAINER ATTENTION rather than ISSUE QUALITY. Requiring `completed`
  controls for attention.

SPLITS (fixed seed -- reproducible)
  dev  60%  -- iterate the rubric against this
  test 40%  -- touched ONCE, at the end of Phase 7
  MLflow is NOT in this file. It is sealed as the transfer test.

KNOWN LIMITATION (goes in the README)
  GitHub returns the CURRENT body. If an author edited theirs to add the
  missing details after being asked, a positive example now looks complete.
  Not cheaply detectable via REST. Spot-check for "EDIT:"/"UPDATE:" markers
  when hand-verifying and drop those.

Usage:
    python scripts/build_calibration_set.py
    python scripts/build_calibration_set.py --per-class 80
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
API = "https://api.github.com"
FIXTURES = Path("data/fixtures")
SEARCH_DELAY = 2.2          # search API allows ~30 req/min
random.seed(42)

# Chosen for ECOSYSTEM DIVERSITY, not raw volume. A judge that agrees with
# maintainers across four languages and four triage cultures has demonstrated
# generalisation. One tuned to a single repo has learned that repo's house style.
CORPUS = [
    ("pandas-dev/pandas",         "Needs Info",                "scientific-python"),
    ("kubernetes/kubernetes",     "triage/needs-information",  "infrastructure-go"),
    ("angular/angular",           "needs reproduction",        "frontend-typescript"),
    ("ray-project/ray",           "needs-repro-script",        "mlops-python"),
    ("gradio-app/gradio",         "needs repro",               "ml-tooling-python"),
]

MIN_BODY_CHARS = 30   # drop near-empty issues: nothing to judge either way


def headers() -> dict:
    if not TOKEN:
        sys.exit("ERROR: GITHUB_TOKEN missing.")
    return {"Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def search(client: httpx.Client, query: str, want: int) -> list[dict]:
    """Paged search. `is:issue` already excludes pull requests."""
    out: list[dict] = []
    for page in range(1, 6):
        r = client.get(f"{API}/search/issues",
                       params={"q": query, "per_page": 100, "page": page},
                       headers=headers(), timeout=30)
        time.sleep(SEARCH_DELAY)
        if r.status_code == 403:
            print("      (rate limited, pausing 60s)")
            time.sleep(60)
            continue
        if r.status_code != 200:
            print(f"      search failed: {r.status_code}")
            break
        items = r.json().get("items", [])
        if not items:
            break
        out.extend(items)
        if len(out) >= want * 3:      # over-fetch, filter, then sample
            break
    return out


def usable(item: dict) -> bool:
    if (item.get("user") or {}).get("type") == "Bot":
        return False
    body = item.get("body") or ""
    return len(body.strip()) >= MIN_BODY_CHARS


def record(item: dict, repo: str, label: str, ecosystem: str, source_label: str) -> dict:
    return {
        "repo": repo,
        "ecosystem": ecosystem,
        "number": item["number"],
        "title": item["title"],
        "body": (item.get("body") or "")[:8000],   # cap: some issues paste huge logs
        "label": label,                            # needs_info | actionable
        "source_label": source_label,              # the maintainer label, or 'closed:completed'
        "created_at": item["created_at"],
        "comments": item.get("comments", 0),
        "html_url": item["html_url"],
        "verified_by_human": False,                # you flip this during spot-check
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=60,
                    help="examples per class per repo")
    args = ap.parse_args()

    FIXTURES.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    with httpx.Client(follow_redirects=True) as client:
        for repo, ni_label, ecosystem in CORPUS:
            print(f"\n{repo}  [{ecosystem}]")

            # --- positives: maintainer said "not actionable as filed" ---
            q_pos = f'repo:{repo} is:issue label:"{ni_label}"'
            pos = [i for i in search(client, q_pos, args.per_class) if usable(i)]
            pos = random.sample(pos, min(args.per_class, len(pos)))
            print(f"  positives (needs info) : {len(pos)}")

            # --- negatives: worked through to completion, never flagged ---
            q_neg = (f'repo:{repo} is:issue is:closed reason:completed '
                     f'-label:"{ni_label}"')
            neg = [i for i in search(client, q_neg, args.per_class) if usable(i)]
            neg = random.sample(neg, min(args.per_class, len(neg)))
            print(f"  negatives (actionable) : {len(neg)}")

            for i in pos:
                rows.append(record(i, repo, "needs_info", ecosystem, ni_label))
            for i in neg:
                rows.append(record(i, repo, "actionable", ecosystem, "closed:completed"))

    if not rows:
        sys.exit("No rows built -- check token and label names.")

    # Split per (repo, class) so both splits stay balanced across ecosystems.
    random.shuffle(rows)
    buckets: dict[tuple, list] = {}
    for r in rows:
        buckets.setdefault((r["repo"], r["label"]), []).append(r)

    dev, test = [], []
    for bucket in buckets.values():
        cut = int(len(bucket) * 0.6)
        dev.extend(bucket[:cut])
        test.extend(bucket[cut:])

    for name, data in (("calibration_dev", dev), ("calibration_test", test)):
        path = FIXTURES / f"{name}.jsonl"
        with path.open("w") as f:
            for r in data:
                f.write(json.dumps(r) + "\n")
        pos_n = sum(1 for r in data if r["label"] == "needs_info")
        print(f"\n{path}: {len(data)} rows  ({pos_n} needs_info / "
              f"{len(data) - pos_n} actionable)")

    print(f"\n{'=' * 58}")
    print(f"  total examples : {len(rows)}")
    print(f"  ecosystems     : {len({r['ecosystem'] for r in rows})}")
    print("\n  CLASS BALANCE NOTE (for the README):")
    print("  This set is ~50/50 by construction. Real prevalence of needs-info")
    print("  is ~3%. Agreement measured here is therefore NOT deployment")
    print("  precision -- in production, false positives will dominate. Report")
    print("  the balanced number, state the real prevalence, and say so.")
    print("\n  NEXT: hand-verify ~30 rows. Set verified_by_human=true, and drop")
    print("  any positive whose body was clearly edited to add the missing")
    print("  details ('EDIT:' / 'UPDATE:') -- those labels no longer match.")
    print("  MLflow is NOT here. It stays sealed as the transfer test.")


if __name__ == "__main__":
    main()
