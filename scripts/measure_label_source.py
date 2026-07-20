#!/usr/bin/env python3
"""
measure_label_source.py -- Phase 0: WHO applied the type label?

Follow-up to measure_label_lag.py, which returned a median lag of 0.00 hours.
No human labels that fast. Something automated is doing it, and the identity of
that something decides what our "ground truth" actually is:

  BOT            -> automation. No human judgement in the label at all.
  ISSUE AUTHOR   -> self-declared, almost certainly via an issue template
                    ("Bug Report" auto-attaches `bug`). Noisy: people file
                    feature requests through the bug template constantly.
  SOMEONE ELSE   -> genuine maintainer judgement. Original ground-truth
                    assumption holds; only the lag prediction was wrong.

Also splits by lag, because a repo can do both: instant template label at
creation, maintainer correction later. Labels applied AFTER creation are the
interesting ones -- that is where human judgement lives.

Usage:
    python scripts/measure_label_source.py --sample 80
"""

import argparse
import json
import os
import random
import sys
from collections import Counter
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
INSTANT_THRESHOLD_MIN = 2      # <=2 min after creation counts as "at creation"
random.seed(42)


def headers() -> dict:
    if not TOKEN:
        sys.exit("ERROR: GITHUB_TOKEN missing.")
    return {"Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def load_type_labels(repo: str) -> set[str]:
    tax = yaml.safe_load(TAXONOMY.read_text())
    block = tax["repos"].get(repo, {})
    out: set[str] = set()
    for canonical in tax["canonical_types"]:
        out.update(n.lower() for n in block.get(canonical, []) or [])
    return out


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def inspect(client, repo, number, type_labels) -> dict | None:
    """Return who applied the first type label, how long after creation, and
    whether the label was ever changed afterwards."""
    issue_r = client.get(f"{API}/repos/{repo}/issues/{number}",
                         headers=headers(), timeout=30)
    if issue_r.status_code != 200:
        return None
    issue = issue_r.json()
    opened = parse_ts(issue["created_at"])
    author = (issue.get("user") or {}).get("login", "")

    ev_r = client.get(f"{API}/repos/{repo}/issues/{number}/events",
                      params={"per_page": 100}, headers=headers(), timeout=30)
    if ev_r.status_code != 200:
        return None
    events = ev_r.json()

    first = None
    later_type_changes = 0
    for ev in events:
        if ev.get("event") not in ("labeled", "unlabeled"):
            continue
        name = (ev.get("label") or {}).get("name", "").lower()
        if name not in type_labels:
            continue
        if first is None and ev["event"] == "labeled":
            actor = ev.get("actor") or {}
            first = {
                "actor_login": actor.get("login", ""),
                "actor_type": actor.get("type", ""),
                "minutes": (parse_ts(ev["created_at"]) - opened).total_seconds() / 60.0,
            }
        elif first is not None:
            later_type_changes += 1

    if first is None:
        return None

    if first["actor_type"] == "Bot" or first["actor_login"].endswith("[bot]"):
        source = "bot"
    elif first["actor_login"] and first["actor_login"] == author:
        source = "author (self-declared)"
    else:
        source = "other party (maintainer)"

    return {
        "source": source,
        "instant": first["minutes"] <= INSTANT_THRESHOLD_MIN,
        "corrected_later": later_type_changes > 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=80)
    args = ap.parse_args()

    files = sorted(RAW_DIR.glob("*.jsonl"))
    if not files:
        sys.exit("No data in data/raw/. Run fetch_issues.py first.")

    grand = Counter()
    grand_instant = Counter()
    grand_corrected = 0
    grand_total = 0

    with httpx.Client(follow_redirects=True) as client:
        for path in files:
            repo = path.stem.replace("__", "/")
            type_labels = load_type_labels(repo)
            if not type_labels:
                continue

            issues = [json.loads(l) for l in path.open()]
            labelled = [i for i in issues
                        if any(l.lower() in type_labels for l in i["labels"])]
            if not labelled:
                continue

            sample = random.sample(labelled, min(args.sample, len(labelled)))
            print(f"\n{'=' * 58}\n{repo}\n{'=' * 58}")
            print(f"  sampling {len(sample)} labelled issues...")

            src = Counter()
            instant_src = Counter()
            corrected = 0
            n = 0
            for idx, issue in enumerate(sample, 1):
                res = inspect(client, repo, issue["number"], type_labels)
                print(f"    {idx}/{len(sample)}", end="\r")
                if not res:
                    continue
                n += 1
                src[res["source"]] += 1
                if res["instant"]:
                    instant_src[res["source"]] += 1
                if res["corrected_later"]:
                    corrected += 1

            if not n:
                print("  no data recovered")
                continue

            print("  who applied the FIRST type label:")
            for source, count in src.most_common():
                print(f"    {source:26s} {count:4d}  ({100*count/n:5.1f}%)")
            inst = sum(instant_src.values())
            print(f"  applied at creation (<={INSTANT_THRESHOLD_MIN} min): "
                  f"{inst}/{n} ({100*inst/n:.1f}%)")
            print(f"  type label changed later      : "
                  f"{corrected}/{n} ({100*corrected/n:.1f}%)  <- human correction signal")

            grand.update(src)
            grand_instant.update(instant_src)
            grand_corrected += corrected
            grand_total += n

    print(f"\n\n{'=' * 58}\nOVERALL\n{'=' * 58}")
    if not grand_total:
        return
    for source, count in grand.most_common():
        print(f"  {source:26s} {count:4d}  ({100*count/grand_total:5.1f}%)")
    inst = sum(grand_instant.values())
    print(f"\n  applied at creation : {inst}/{grand_total} ({100*inst/grand_total:.1f}%)")
    print(f"  corrected later     : {grand_corrected}/{grand_total} "
          f"({100*grand_corrected/grand_total:.1f}%)")

    print("\n  INTERPRETATION")
    auth = grand["author (self-declared)"] + grand["bot"]
    if 100 * auth / grand_total > 50:
        print("  Majority of labels are self-declared or automated, not maintainer")
        print("  judgement. Ground truth is NOISY: treat labels as the author's")
        print("  claim about their own issue. The classifier's job becomes")
        print("  VERIFICATION (does the content match the declared type?) plus")
        print("  fallback for the ~29% with no label at all.")
        print("  -> The 'corrected later' % is your best estimate of how often")
        print("     the self-declared label is actually wrong.")
    else:
        print("  Majority of labels come from a third party -- genuine maintainer")
        print("  judgement. Original ground-truth assumption holds; only the")
        print("  speed prediction was wrong. Classifier remains a fallback for")
        print("  the ~29% never labelled.")


if __name__ == "__main__":
    main()
