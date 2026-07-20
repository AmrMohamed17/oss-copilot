#!/usr/bin/env python3
"""
build_calibration_set_v2.py -- author-matched calibration set.

WHY v2
  v1 measured a 39.3-point insider gap between classes:
      actionable  51.3% insider
      needs_info  12.0% insider
  Kubernetes was worst: 71.7% vs 13.3%. An LLM judge could score well on v1 by
  detecting insider writing style ("[Serve]" prefixes, internal jargon,
  "Proposed Fix" sections) instead of assessing information sufficiency --
  shortcut learning that would collapse in deployment, where nearly every
  watched issue comes from an outsider.

THE FIX
  Restrict BOTH classes to author_association == NONE (no prior merged PR in
  that repo). Insider status is then constant across the exam and carries zero
  information. The only way to score well is to actually read the content.

  This is controlling for a confounder: hold the nuisance variable fixed so the
  effect of interest is the only thing that varies.

  It also makes the set MORE deployment-realistic, not less -- 88% of real
  needs-info issues are outsider-authored, and outsiders are exactly the
  population this product watches.

v1 files are PRESERVED as *_v1_confounded.jsonl. They are the evidence that the
confound was found and fixed -- worth more than a clean dataset with no story.

Usage:
    python scripts/build_calibration_set_v2.py
"""

import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
API = "https://api.github.com"
FIXTURES = Path("data/fixtures")
SEARCH_DELAY = 2.2
PER_CLASS = 60
OVERFETCH_PAGES = 6        # over-fetch, then filter to outsiders, then sample
MIN_BODY_CHARS = 30
random.seed(42)

CORPUS = [
    ("pandas-dev/pandas",     "Needs Info",               "scientific-python"),
    ("kubernetes/kubernetes", "triage/needs-information", "infrastructure-go"),
    ("angular/angular",       "needs reproduction",       "frontend-typescript"),
    ("ray-project/ray",       "needs-repro-script",       "mlops-python"),
    ("gradio-app/gradio",     "needs repro",              "ml-tooling-python"),
]

OUTSIDER_ONLY = {"NONE"}   # no prior merged PR in this repo


def headers() -> dict:
    if not TOKEN:
        sys.exit("ERROR: GITHUB_TOKEN missing.")
    return {"Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def search(client: httpx.Client, query: str) -> list[dict]:
    out: list[dict] = []
    for page in range(1, OVERFETCH_PAGES + 1):
        r = client.get(f"{API}/search/issues",
                       params={"q": query, "per_page": 100, "page": page},
                       headers=headers(), timeout=30)
        time.sleep(SEARCH_DELAY)
        if r.status_code == 403:
            print("      rate limited, pausing 60s")
            time.sleep(60)
            continue
        if r.status_code != 200:
            break
        items = r.json().get("items", [])
        if not items:
            break
        out.extend(items)
    return out


def usable(item: dict) -> bool:
    if (item.get("user") or {}).get("type") == "Bot":
        return False
    if item.get("author_association") not in OUTSIDER_ONLY:
        return False
    return len((item.get("body") or "").strip()) >= MIN_BODY_CHARS


def record(item, repo, label, ecosystem, source_label) -> dict:
    return {
        "repo": repo,
        "ecosystem": ecosystem,
        "number": item["number"],
        "title": item["title"],
        "body": (item.get("body") or "")[:8000],
        "label": label,
        "source_label": source_label,
        "author_association": item.get("author_association", "UNKNOWN"),
        "created_at": item["created_at"],
        "comments": item.get("comments", 0),
        "html_url": item["html_url"],
        "verified_by_human": False,
    }


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)

    # preserve v1 as evidence
    for name in ("calibration_dev", "calibration_test"):
        src = FIXTURES / f"{name}.jsonl"
        if src.exists():
            dst = FIXTURES / f"{name}_v1_confounded.jsonl"
            if not dst.exists():
                src.rename(dst)
                print(f"preserved {src.name} -> {dst.name}")

    rows: list[dict] = []
    with httpx.Client(follow_redirects=True) as client:
        for repo, ni_label, ecosystem in CORPUS:
            print(f"\n{repo}  [{ecosystem}]")

            pos_raw = search(client, f'repo:{repo} is:issue label:"{ni_label}"')
            pos = [i for i in pos_raw if usable(i)]
            print(f"  positives: {len(pos_raw)} fetched -> {len(pos)} outsider-authored")
            pos = random.sample(pos, min(PER_CLASS, len(pos)))

            neg_raw = search(client, f'repo:{repo} is:issue is:closed '
                                     f'reason:completed -label:"{ni_label}"')
            neg = [i for i in neg_raw if usable(i)]
            print(f"  negatives: {len(neg_raw)} fetched -> {len(neg)} outsider-authored")
            neg = random.sample(neg, min(PER_CLASS, len(neg)))

            print(f"  keeping {len(pos)} positive / {len(neg)} negative")
            for i in pos:
                rows.append(record(i, repo, "needs_info", ecosystem, ni_label))
            for i in neg:
                rows.append(record(i, repo, "actionable", ecosystem, "closed:completed"))

    if not rows:
        sys.exit("No rows built.")

    random.shuffle(rows)
    buckets: dict[tuple, list] = {}
    for r in rows:
        buckets.setdefault((r["repo"], r["label"]), []).append(r)

    dev, test = [], []
    for b in buckets.values():
        cut = int(len(b) * 0.6)
        dev.extend(b[:cut])
        test.extend(b[cut:])

    for name, data in (("calibration_dev", dev), ("calibration_test", test)):
        path = FIXTURES / f"{name}.jsonl"
        with path.open("w") as f:
            for r in data:
                f.write(json.dumps(r) + "\n")
        pos_n = sum(1 for r in data if r["label"] == "needs_info")
        print(f"\n{path}: {len(data)} rows ({pos_n} needs_info / {len(data)-pos_n} actionable)")

    # confirm the confound is gone
    print(f"\n{'=' * 58}\nCONFOUND CHECK\n{'=' * 58}")
    for label in ("needs_info", "actionable"):
        c = Counter(r["author_association"] for r in rows if r["label"] == label)
        n = sum(c.values())
        print(f"  {label:11s} n={n:4d}  " + ", ".join(f"{k}={v}" for k, v in c.most_common()))
    print("\n  Both classes are now 100% outsider-authored (author_association=NONE).")
    print("  Insider status is constant -> it carries no signal -> the judge")
    print("  cannot use writing style as a shortcut.")
    print("\n  README line:")
    print('  "v1 of the calibration set showed a 39.3-point insider-authorship')
    print('   gap between classes (51.3% vs 12.0%), meaning a judge could score')
    print('   well by detecting writing style rather than information')
    print('   sufficiency. v2 matches both classes on author_association=NONE,')
    print('   eliminating the shortcut and matching deployment conditions."')


if __name__ == "__main__":
    main()
