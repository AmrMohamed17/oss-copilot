#!/usr/bin/env python3
"""
audit_ground_truth.py -- Phase 0 FINAL audit. Then we lock the design.

measure_label_source.py established that 90.7% of type labels are applied by
the issue AUTHOR at creation (templates). So type labels are a self-declared
claim, not maintainer judgement -- too weak to carry Layer A's headline metric.

This script asks whether GENUINE maintainer-judgement ground truth exists, and
in what volume, for the two components that actually justify an agent:

  1. DUPLICATE DETECTION
     Ground truth: state_reason == "duplicate". A maintainer decided this issue
     duplicates another. Real human decision, recorded by GitHub. FREE to count.

  2. REPRODUCTION-READINESS
     Ground truth: a needs-info label applied BY SOMEONE OTHER THAN THE AUTHOR.
     If a maintainer had to ask for more information, the issue was not
     reproducible as filed. Requires the events API -> sampled.

  3. REAL TYPE CORRECTIONS (fixing the earlier bug)
     The previous script counted ANY later type-label event as a "correction".
     Langfuse's bug -> unconfirmed-bug workflow inflated this to 93.8%. Here we
     compare CANONICAL types before and after: only bug -> feature counts, not
     bug -> unconfirmed bug.

Volume needed: ~50+ positive examples per signal to evaluate anything.

Usage:
    python scripts/audit_ground_truth.py --sample 60
"""

import argparse
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
API = "https://api.github.com"
RAW_DIR = Path("data/raw")
TAXONOMY = Path("data/taxonomy/v1.yaml")
MIN_VIABLE = 50
random.seed(42)


def headers() -> dict:
    if not TOKEN:
        sys.exit("ERROR: GITHUB_TOKEN missing.")
    return {"Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def load_tax() -> dict:
    return yaml.safe_load(TAXONOMY.read_text())


def canonical_of(repo: str, label: str, tax: dict) -> str | None:
    """Map a raw label name to its canonical TYPE, or None if it is meta."""
    block = tax["repos"].get(repo, {})
    low = label.lower()
    for canonical in tax["canonical_types"]:
        if low in [n.lower() for n in block.get(canonical, []) or []]:
            return canonical
    return None


def needs_info_names(tax: dict) -> set[str]:
    return {n.lower() for n in tax["meta_labels"].get("needs_info", [])}


def real_type_correction(client, repo, number, tax) -> bool | None:
    """Did the CANONICAL type actually change after the first assignment?"""
    r = client.get(f"{API}/repos/{repo}/issues/{number}/events",
                   params={"per_page": 100}, headers=headers(), timeout=30)
    if r.status_code != 200:
        return None
    first = None
    for ev in r.json():
        if ev.get("event") != "labeled":
            continue
        canon = canonical_of(repo, (ev.get("label") or {}).get("name", ""), tax)
        if canon is None:
            continue
        if first is None:
            first = canon
        elif canon != first:
            return True          # genuine recategorisation
    return False if first else None


def needs_info_by_other(client, repo, number, author, ni_names) -> bool | None:
    """Was a needs-info label applied by someone other than the issue author?"""
    r = client.get(f"{API}/repos/{repo}/issues/{number}/events",
                   params={"per_page": 100}, headers=headers(), timeout=30)
    if r.status_code != 200:
        return None
    for ev in r.json():
        if ev.get("event") != "labeled":
            continue
        if (ev.get("label") or {}).get("name", "").lower() not in ni_names:
            continue
        actor = (ev.get("actor") or {}).get("login", "")
        if actor and actor != author:
            return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=60)
    args = ap.parse_args()

    tax = load_tax()
    ni_names = needs_info_names(tax)
    files = sorted(RAW_DIR.glob("*.jsonl"))
    if not files:
        sys.exit("No data in data/raw/. Run fetch_issues.py first.")

    tot_issues = tot_dupes = 0
    tot_ni_labelled = 0
    corr_yes = corr_n = 0
    ni_yes = ni_n = 0

    with httpx.Client(follow_redirects=True) as client:
        for path in files:
            repo = path.stem.replace("__", "/")
            issues = [json.loads(l) for l in path.open()]
            n = len(issues)
            tot_issues += n

            # --- FREE from cached data ---
            dupes = [i for i in issues if i.get("state_reason") == "duplicate"]
            ni_flagged = [i for i in issues
                          if any(l.lower() in ni_names for l in i["labels"])]
            tot_dupes += len(dupes)
            tot_ni_labelled += len(ni_flagged)

            print(f"\n{'=' * 58}\n{repo}\n{'=' * 58}")
            print(f"  issues                    : {n}")
            print(f"  closed as DUPLICATE       : {len(dupes)}  ({100*len(dupes)/n:.1f}%)"
                  f"   <- maintainer judgement")
            print(f"  carrying a NEEDS-INFO lbl : {len(ni_flagged)}  "
                  f"({100*len(ni_flagged)/n:.1f}%)")

            # --- sampled: was needs-info applied by a non-author? ---
            if ni_flagged:
                s = random.sample(ni_flagged, min(20, len(ni_flagged)))
                hits = 0
                checked = 0
                for i in s:
                    res = needs_info_by_other(client, repo, i["number"],
                                              i.get("author_login", ""), ni_names)
                    if res is not None:
                        checked += 1
                        hits += bool(res)
                if checked:
                    ni_yes += hits
                    ni_n += checked
                    print(f"    of {checked} sampled, applied by a NON-AUTHOR: "
                          f"{hits} ({100*hits/checked:.0f}%)")

            # --- sampled: real canonical type corrections ---
            labelled = [i for i in issues
                        if any(canonical_of(repo, l, tax) for l in i["labels"])]
            if labelled:
                s = random.sample(labelled, min(args.sample, len(labelled)))
                yes = checked = 0
                for idx, i in enumerate(s, 1):
                    res = real_type_correction(client, repo, i["number"], tax)
                    print(f"    type-correction check {idx}/{len(s)}", end="\r")
                    if res is not None:
                        checked += 1
                        yes += bool(res)
                if checked:
                    corr_yes += yes
                    corr_n += checked
                    print(f"  REAL type corrections     : {yes}/{checked} "
                          f"({100*yes/checked:.1f}%)   <- canonical type actually changed")

    print(f"\n\n{'=' * 58}\nGROUND-TRUTH AVAILABILITY\n{'=' * 58}")
    print(f"  total issues                 : {tot_issues}")
    print(f"  duplicates (maintainer)      : {tot_dupes}"
          f"   {'VIABLE' if tot_dupes >= MIN_VIABLE else 'TOO FEW'}")
    print(f"  needs-info labelled          : {tot_ni_labelled}"
          f"   {'VIABLE' if tot_ni_labelled >= MIN_VIABLE else 'TOO FEW'}")
    if ni_n:
        print(f"    ...of which non-author     : {100*ni_yes/ni_n:.0f}% of sampled")
    if corr_n:
        print(f"  real type corrections        : {100*corr_yes/corr_n:.1f}% "
              f"(was 27.4% with the broken metric)")

    print("\n  DECISION")
    if tot_dupes >= MIN_VIABLE:
        print("  - Duplicate detection HAS real maintainer ground truth. Keep it,")
        print("    and promote it to a Layer A headline metric.")
    else:
        print("  - Too few duplicates. Cut dedupe (Gate B fails) and say so.")
    if tot_ni_labelled >= MIN_VIABLE:
        print("  - Reproduction-readiness HAS ground truth. This becomes Layer A's")
        print("    strongest component: maintainer-verified, agent-shaped work.")
    else:
        print("  - Needs-info labels too rare for supervised eval. Fall back to")
        print("    LLM-as-judge against a rubric, calibrated on a human spot-check,")
        print("    and label the metric honestly as softer.")
    print("  - Classifier: demote to cheap fallback for the ~29% unlabelled,")
    print("    reported against author-declared labels WITH that caveat stated.")


if __name__ == "__main__":
    main()
