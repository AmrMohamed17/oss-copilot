#!/usr/bin/env python3
"""
check_author_confound.py -- is the calibration set separable by AUTHOR rather
than by ACTIONABILITY?

THE WORRY
  Negatives were selected by "closed as completed". Issues written by people who
  know the project get completed more often -- they know what to include, and
  frequently fix it themselves. Positives (needs-info) skew toward newcomers.

  So the two classes may differ along TWO axes at once: actionability, and who
  wrote it. Insider issues carry loud surface tells ("[Serve]" prefixes, internal
  jargon, "Proposed Fix" sections). Those are FAR easier for an LLM to detect
  than whether enough information is present.

  A judge that learns "sounds like a team member" would score well here and fail
  in deployment, where nearly every watched issue comes from an outsider -- and
  it would filter away exactly the newcomer-filed issues you want to find.

  This is shortcut learning: a feature that correlates with the label in your
  data but is not the thing you meant.

THE TEST
  GitHub returns `author_association` on every issue. Enrich both fixture files
  in place (preserving any hand-verification already done), then compare insider
  rates across the two classes.

  Small gap  -> worry dissolves, closed with evidence.
  Large gap  -> real confound. Rebalance on author type, or state it as a
                measured limitation in the README.

Usage:
    python scripts/check_author_confound.py            # enrich then report
    python scripts/check_author_confound.py --report   # report only
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
API = "https://api.github.com"
FILES = [Path("data/fixtures/calibration_dev.jsonl"),
         Path("data/fixtures/calibration_test.jsonl")]

# GitHub's author_association values, grouped by how "inside" the author is.
CORE = {"OWNER", "MEMBER", "COLLABORATOR"}
RETURNING = {"CONTRIBUTOR"}          # has had a PR merged before
OUTSIDER = {"NONE", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "MANNEQUIN"}


def headers() -> dict:
    if not TOKEN:
        sys.exit("ERROR: GITHUB_TOKEN missing.")
    return {"Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def tier(assoc: str) -> str:
    if assoc in CORE:
        return "core"
    if assoc in RETURNING:
        return "returning"
    return "outsider"


def enrich(client: httpx.Client, path: Path) -> None:
    rows = [json.loads(l) for l in path.open()]
    todo = [r for r in rows if "author_association" not in r]
    if not todo:
        print(f"  {path.name}: already enriched")
        return

    print(f"  {path.name}: fetching {len(todo)} rows")
    for idx, row in enumerate(todo, 1):
        r = client.get(f"{API}/repos/{row['repo']}/issues/{row['number']}",
                       headers=headers(), timeout=30)
        if r.status_code == 403:
            print("    rate limited -- pausing 60s")
            time.sleep(60)
            continue
        if r.status_code == 200:
            row["author_association"] = r.json().get("author_association", "UNKNOWN")
        else:
            row["author_association"] = "UNKNOWN"
        print(f"    {idx}/{len(todo)}", end="\r")

    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"    done -> {path}")


def report() -> None:
    rows = []
    for p in FILES:
        if p.exists():
            rows.extend(json.loads(l) for l in p.open())
    rows = [r for r in rows if "author_association" in r]
    if not rows:
        print("Nothing enriched yet.")
        return

    by_class: dict[str, Counter] = defaultdict(Counter)
    by_repo: dict[tuple, Counter] = defaultdict(Counter)
    raw: dict[str, Counter] = defaultdict(Counter)

    for r in rows:
        t = tier(r["author_association"])
        by_class[r["label"]][t] += 1
        by_repo[(r["repo"], r["label"])][t] += 1
        raw[r["label"]][r["author_association"]] += 1

    print(f"\n{'=' * 62}\nAUTHOR TIER BY CLASS\n{'=' * 62}")
    insider_rate = {}
    for label in ("needs_info", "actionable"):
        c = by_class[label]
        n = sum(c.values())
        if not n:
            continue
        ins = 100 * (c["core"] + c["returning"]) / n
        insider_rate[label] = ins
        print(f"\n  {label}  (n={n})")
        for t in ("core", "returning", "outsider"):
            print(f"    {t:10s} {c[t]:4d}  ({100*c[t]/n:5.1f}%)")
        print(f"    -> insider (core+returning): {ins:.1f}%")

    print(f"\n{'=' * 62}\nRAW author_association\n{'=' * 62}")
    for label in ("needs_info", "actionable"):
        print(f"  {label}: " + ", ".join(
            f"{k}={v}" for k, v in raw[label].most_common()))

    print(f"\n{'=' * 62}\nPER REPO (insider % by class)\n{'=' * 62}")
    repos = sorted({r for r, _ in by_repo})
    for repo in repos:
        line = f"  {repo:26s}"
        for label in ("needs_info", "actionable"):
            c = by_repo[(repo, label)]
            n = sum(c.values())
            if n:
                ins = 100 * (c["core"] + c["returning"]) / n
                line += f"  {label}={ins:5.1f}%"
        print(line)

    print(f"\n{'=' * 62}\nVERDICT\n{'=' * 62}")
    if len(insider_rate) < 2:
        return
    gap = insider_rate["actionable"] - insider_rate["needs_info"]
    print(f"  insider rate, actionable : {insider_rate['actionable']:.1f}%")
    print(f"  insider rate, needs_info : {insider_rate['needs_info']:.1f}%")
    print(f"  gap                      : {gap:+.1f} points\n")

    if gap >= 30:
        print("  STRONG CONFOUND. The classes are largely separable by author")
        print("  type alone. An LLM judge can score well by detecting insider")
        print("  writing style instead of information sufficiency.")
        print("  ACTION: rebuild negatives restricted to outsider-authored")
        print("  issues (author_association NONE/CONTRIBUTOR), so both classes")
        print("  come from comparable populations.")
    elif gap >= 15:
        print("  MODERATE CONFOUND. Worth controlling for. Either rebalance, or")
        print("  report agreement separately for insider- and outsider-authored")
        print("  issues -- the outsider number is the one that matters, since")
        print("  that is what deployment looks like.")
    else:
        print("  NO MEANINGFUL CONFOUND. Classes are comparable on author type;")
        print("  a judge cannot score well on this shortcut alone. Record the")
        print("  number in the README as a checked-and-cleared concern.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if not args.report:
        with httpx.Client(follow_redirects=True) as client:
            for p in FILES:
                if p.exists():
                    enrich(client, p)
    report()


if __name__ == "__main__":
    main()
