#!/usr/bin/env python3
"""
measure_label_lag.py -- Phase 0: does the classifier deserve to exist?

Tests the assumption the whole classifier rests on: that new issues arrive
UNLABELLED and stay that way long enough for early detection to matter.

Two numbers:
  1. NEVER-LABELLED RATE  -- % of issues that never receive a type label.
     Computed free from data/raw/. These issues are invisible to a
     fetch-the-label approach.
  2. TIME-TO-FIRST-TYPE-LABEL -- for issues that DO get labelled, how long did
     it take? Requires the events API (the issue object records current labels,
     not when they were applied), so this is measured on a SAMPLE.

Decision rule, committed to in advance:
  - median lag > ~1 hour AND never-labelled rate > ~20%  -> classifier justified
  - median lag < a few minutes AND never-labelled < 5%   -> DROP the classifier,
    just read labels, and record that in the README as a measured decision.

Usage:
    python scripts/measure_label_lag.py                # all cached repos
    python scripts/measure_label_lag.py --sample 150
"""

import argparse
import json
import os
import random
import statistics
import sys
from datetime import datetime
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
API = "https://api.github.com"
RAW_DIR = Path("data/raw")
TAXONOMY = Path("data/taxonomy/v1.yaml")
random.seed(42)   # reproducible sample -- same issues every run


def headers() -> dict:
    if not TOKEN:
        sys.exit("ERROR: GITHUB_TOKEN missing.")
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load_type_labels(repo: str) -> set[str]:
    """Exact lowercase type labels for this repo, from the taxonomy."""
    tax = yaml.safe_load(TAXONOMY.read_text())
    block = tax["repos"].get(repo, {})
    out: set[str] = set()
    for canonical in tax["canonical_types"]:
        out.update(n.lower() for n in block.get(canonical, []) or [])
    return out


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def first_type_label_lag(client, repo, number, type_labels) -> float | None:
    """Hours between issue creation and the first TYPE label being applied."""
    r = client.get(
        f"{API}/repos/{repo}/issues/{number}/events",
        params={"per_page": 100}, headers=headers(), timeout=30,
    )
    if r.status_code != 200:
        return None
    created = None
    for ev in r.json():
        if ev.get("event") != "labeled":
            continue
        name = (ev.get("label") or {}).get("name", "").lower()
        if name in type_labels:
            created = parse_ts(ev["created_at"])
            break
    if created is None:
        return None

    issue = client.get(f"{API}/repos/{repo}/issues/{number}",
                       headers=headers(), timeout=30)
    if issue.status_code != 200:
        return None
    opened = parse_ts(issue.json()["created_at"])
    return (created - opened).total_seconds() / 3600.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=100,
                    help="labelled issues sampled per repo for the lag measurement")
    args = ap.parse_args()

    files = sorted(RAW_DIR.glob("*.jsonl"))
    if not files:
        sys.exit("No data in data/raw/. Run fetch_issues.py first.")

    all_lags: list[float] = []
    total_issues = total_unlabelled = 0

    with httpx.Client(follow_redirects=True) as client:
        for path in files:
            repo = path.stem.replace("__", "/")
            type_labels = load_type_labels(repo)
            if not type_labels:
                print(f"\n{repo}: no type labels in taxonomy -- skipped")
                continue

            issues = [json.loads(line) for line in path.open()]
            labelled, unlabelled = [], 0
            for i in issues:
                if any(l.lower() in type_labels for l in i["labels"]):
                    labelled.append(i)
                else:
                    unlabelled += 1

            n = len(issues)
            total_issues += n
            total_unlabelled += unlabelled
            never_rate = 100 * unlabelled / n if n else 0

            print(f"\n{'=' * 58}\n{repo}\n{'=' * 58}")
            print(f"  issues                  : {n}")
            print(f"  never got a type label  : {unlabelled}  ({never_rate:.1f}%)")

            sample = random.sample(labelled, min(args.sample, len(labelled)))
            print(f"  sampling {len(sample)} for lag (2 API calls each)...")

            lags = []
            for idx, issue in enumerate(sample, 1):
                lag = first_type_label_lag(client, repo, issue["number"], type_labels)
                if lag is not None and lag >= 0:
                    lags.append(lag)
                print(f"    {idx}/{len(sample)}", end="\r")

            if lags:
                all_lags.extend(lags)
                lags.sort()
                within_1h = 100 * sum(1 for l in lags if l <= 1) / len(lags)
                within_24h = 100 * sum(1 for l in lags if l <= 24) / len(lags)
                print(f"  median time-to-type-label: {statistics.median(lags):8.2f} h")
                print(f"  25th / 75th percentile   : "
                      f"{lags[len(lags)//4]:.2f} h / {lags[3*len(lags)//4]:.2f} h")
                print(f"  labelled within 1 hour   : {within_1h:.1f}%")
                print(f"  labelled within 24 hours : {within_24h:.1f}%")
            else:
                print("  no lag data recovered")

    print(f"\n\n{'=' * 58}\nVERDICT\n{'=' * 58}")
    if total_issues:
        overall_never = 100 * total_unlabelled / total_issues
        print(f"  overall never-labelled : {overall_never:.1f}%  ({total_unlabelled}/{total_issues})")
    if all_lags:
        med = statistics.median(all_lags)
        fast = 100 * sum(1 for l in all_lags if l <= 1) / len(all_lags)
        print(f"  overall median lag     : {med:.2f} h")
        print(f"  labelled within 1 hour : {fast:.1f}%")
        print()
        if med > 1 and overall_never > 20:
            print("  -> CLASSIFIER JUSTIFIED. Issues arrive unlabelled and stay")
            print("     that way; waiting for maintainers means arriving late,")
            print("     and a large share are never labelled at all.")
        else:
            print("  -> RECONSIDER. Labelling is fast and near-complete here.")
            print("     Reading labels may beat classifying them. Record this.")
    print("\n  Put these numbers in the README under Design decisions.")


if __name__ == "__main__":
    main()
