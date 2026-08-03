#!/usr/bin/env python3
"""
run_baseline.py -- Phase 2: measure the single-agent readiness baseline.

Runs the baseline judge over the calibration DEV set and scores agreement with
maintainer ground truth. This number is the floor Phase 3 must beat.

DISCIPLINE:
- DEV set only. calibration_test.jsonl and MLflow's 40 stay SEALED until Phase 7.
  Iterating the rubric against test would contaminate the final number.
- Results cached per issue so re-scoring is free and re-runs don't re-bill the API.
- Reports the BALANCED number AND restates real-world prevalence (~3%), because
  50/50 agreement is not deployment precision.

Usage:
    python scripts/run_baseline.py            # run + score dev set
    python scripts/run_baseline.py --score    # re-score cached results only
    python scripts/run_baseline.py --limit 20 # smoke test on 20 issues
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, "src")
from oss_copilot.readiness.judge import judge_issue
from oss_copilot.readiness.rubric import RUBRIC_VERSION

DEV = Path("data/fixtures/calibration_dev.jsonl")
CACHE = Path(f"data/results/baseline_{RUBRIC_VERSION}.jsonl")

# ground-truth label -> our verdict vocabulary
GT_MAP = {"needs_info": "needs_info", "actionable": "actionable"}


def load_dev() -> list[dict]:
    return [json.loads(l) for l in DEV.open()]


def load_cache() -> dict:
    if not CACHE.exists():
        return {}
    out = {}
    for line in CACHE.open():
        r = json.loads(line)
        out[(r["repo"], r["number"])] = r
    return out


def run(limit: int | None) -> None:
    dev = load_dev()
    if limit:
        dev = dev[:limit]
    cache = load_cache()
    CACHE.parent.mkdir(parents=True, exist_ok=True)

    todo = [d for d in dev if (d["repo"], d["number"]) not in cache]
    print(f"dev issues: {len(dev)} | cached: {len(dev)-len(todo)} | to run: {len(todo)}")

    errors = 0
    with CACHE.open("a") as f:
        for i, issue in enumerate(todo, 1):
            res = judge_issue(issue["title"], issue["body"])
            row = {
                "repo": issue["repo"], "number": issue["number"],
                "ecosystem": issue["ecosystem"],
                "ground_truth": issue["label"],
                "verdict": res.get("verdict"),
                "reason": res.get("reason"),
                "error": res.get("error"),
            }
            if res.get("error"):
                errors += 1
            f.write(json.dumps(row) + "\n"); f.flush()
            print(f"  {i}/{len(todo)}  {issue['repo']}#{issue['number']}"
                  f"  -> {res.get('verdict') or res.get('error')}", end="\r")
            time.sleep(0.3)   # gentle on the API
    print(f"\ndone. errors: {errors}")
    score()


def score() -> None:
    dev_keys = {(d["repo"], d["number"]) for d in load_dev()}
    rows = [r for r in load_cache().values() if (r["repo"], r["number"]) in dev_keys]
    rows = [r for r in rows if not r.get("error") and r.get("verdict")]
    if not rows:
        print("no scored rows yet."); return

    n = len(rows)
    correct = sum(1 for r in rows if r["verdict"] == GT_MAP[r["ground_truth"]])

    # confusion matrix (positive class = needs_info)
    tp = sum(1 for r in rows if r["ground_truth"]=="needs_info" and r["verdict"]=="needs_info")
    fn = sum(1 for r in rows if r["ground_truth"]=="needs_info" and r["verdict"]=="actionable")
    fp = sum(1 for r in rows if r["ground_truth"]=="actionable" and r["verdict"]=="needs_info")
    tn = sum(1 for r in rows if r["ground_truth"]=="actionable" and r["verdict"]=="actionable")

    prec = tp/(tp+fp) if tp+fp else 0
    rec  = tp/(tp+fn) if tp+fn else 0
    f1   = 2*prec*rec/(prec+rec) if prec+rec else 0

    print(f"\n{'='*54}\nBASELINE — rubric {RUBRIC_VERSION}  (dev, n={n})\n{'='*54}")
    print(f"  agreement with maintainers : {100*correct/n:.1f}%  ({correct}/{n})")
    print(f"\n  needs_info as positive class:")
    print(f"    precision : {prec:.3f}")
    print(f"    recall    : {rec:.3f}")
    print(f"    F1        : {f1:.3f}")
    print(f"\n  confusion matrix:")
    print(f"                    predicted")
    print(f"                 needs_info  actionable")
    print(f"    GT needs_info   {tp:4d}      {fn:4d}")
    print(f"    GT actionable   {fp:4d}      {tn:4d}")

    # per-ecosystem agreement -> does it generalize, or lean on one repo's style?
    print(f"\n  per-ecosystem agreement:")
    by_eco = {}
    for r in rows:
        by_eco.setdefault(r["ecosystem"], []).append(r)
    for eco, rs in sorted(by_eco.items()):
        c = sum(1 for r in rs if r["verdict"]==GT_MAP[r["ground_truth"]])
        print(f"    {eco:22s} {100*c/len(rs):5.1f}%  ({c}/{len(rs)})")

    print(f"\n  READ THIS NUMBER HONESTLY:")
    print(f"  - This dev set is 50/50 by construction. Real needs_info prevalence")
    print(f"    is ~3%, so this agreement is NOT deployment precision.")
    print(f"  - This is the BASELINE. Phase 3's multi-agent version must beat it")
    print(f"    by a real margin or it gets cut.")
    print(f"  - Next: read the disagreements (--errors), revise the rubric, re-run.")


def show_disagreements() -> None:
    dev = {(d["repo"],d["number"]): d for d in load_dev()}
    for r in load_cache().values():
        if r.get("error") or r.get("verdict")==GT_MAP.get(r.get("ground_truth"),""):
            continue
        d = dev.get((r["repo"],r["number"]))
        if not d: continue
        print(f"\n{'-'*60}")
        print(f"{r['repo']}#{r['number']}  GT={r['ground_truth']}  PRED={r['verdict']}")
        print(f"reason: {r.get('reason')}")
        print(f"TITLE: {d['title']}")
        print(f"{(d['body'] or '')[:400]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--errors", action="store_true", help="show disagreements")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    if a.score: score()
    elif a.errors: show_disagreements()
    else: run(a.limit)


if __name__ == "__main__":
    main()
