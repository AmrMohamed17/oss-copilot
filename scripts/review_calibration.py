#!/usr/bin/env python3
"""
review_calibration.py -- hand-verify the calibration answer key.

WHY: the labels came from maintainers, but maintainers are not infallible and
GitHub returns the CURRENT issue body -- an author may have edited theirs to add
the missing details after being asked, which breaks a 'needs_info' label.

The output is a NUMBER, not just cleaner data:
    human-verified label accuracy = X%
That is the CEILING on how well the judge can ever score. If the key is 15%
noise, a judge reporting 95% agreement is measuring something else. Goes in the
README next to every readiness metric.

DEV SPLIT ONLY. Reading test-set bodies would shape how you write the rubric,
which is the contamination the split exists to prevent.

Usage:
    python scripts/review_calibration.py --n 30
    python scripts/review_calibration.py --report      # stats only, no review
"""

import argparse
import json
import random
from pathlib import Path

DEV = Path("data/fixtures/calibration_dev.jsonl")
random.seed(42)

BODY_CHARS = 1400
EDIT_MARKERS = ["edit:", "edited:", "update:", "updated:", "edit ", "**edit"]


def load() -> list[dict]:
    return [json.loads(l) for l in DEV.open()]


def save(rows: list[dict]) -> None:
    with DEV.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def report(rows: list[dict]) -> None:
    reviewed = [r for r in rows if r.get("verified_by_human")]
    if not reviewed:
        print("Nothing reviewed yet.")
        return
    confirmed = sum(1 for r in reviewed if r.get("human_verdict") == "confirmed")
    wrong = sum(1 for r in reviewed if r.get("human_verdict") == "wrong")
    edited = sum(1 for r in reviewed if r.get("human_verdict") == "edited")
    n = len(reviewed)

    print(f"\n{'=' * 56}\nLABEL QUALITY (dev split)\n{'=' * 56}")
    print(f"  reviewed            : {n}")
    print(f"  agreed with label   : {confirmed}  ({100*confirmed/n:.1f}%)  <- the ceiling")
    print(f"  label looks wrong   : {wrong}  ({100*wrong/n:.1f}%)")
    print(f"  body edited after   : {edited}  ({100*edited/n:.1f}%)")
    print(f"\n  usable rows remaining: {sum(1 for r in rows if r.get('human_verdict') != 'wrong' and r.get('human_verdict') != 'edited')}"
          f" of {len(rows)}")
    print("\n  README line:")
    print(f'  "Hand-verified {n} calibration labels; agreed with the maintainer')
    print(f'   on {100*confirmed/n:.0f}%. Readiness agreement is reported against')
    print('   this ceiling, not assumed to be a perfect key."')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    rows = load()
    if args.report:
        report(rows)
        return

    todo = [r for r in rows if not r.get("verified_by_human")]
    random.shuffle(todo)
    todo = todo[: args.n]

    print(f"Reviewing {len(todo)} rows. For each, decide whether the LABEL is right.")
    print("  [y] agree with the label")
    print("  [n] label is wrong")
    print("  [e] body was edited later (label no longer matches the text)")
    print("  [s] skip   [q] save and quit\n")

    for idx, row in enumerate(todo, 1):
        body = row["body"][:BODY_CHARS]
        flag = "  <-- possible edit marker" if any(
            m in row["body"][:3000].lower() for m in EDIT_MARKERS) else ""

        print("\n" + "=" * 70)
        print(f"[{idx}/{len(todo)}]  {row['repo']}  #{row['number']}   ({row['ecosystem']})")
        print(f"LABEL: {row['label'].upper()}   (source: {row['source_label']}){flag}")
        print("=" * 70)
        print(f"TITLE: {row['title']}\n")
        print(body)
        if len(row["body"]) > BODY_CHARS:
            print(f"\n... [{len(row['body']) - BODY_CHARS} more chars]")
        print(f"\n{row['html_url']}")

        if row["label"] == "needs_info":
            print("\nQ: could a maintainer act on this AS WRITTEN? "
                  "If NO, the label is right -> y")
        else:
            print("\nQ: could a maintainer act on this AS WRITTEN? "
                  "If YES, the label is right -> y")

        while True:
            ans = input("  [y/n/e/s/q] > ").strip().lower()
            if ans in ("y", "n", "e", "s", "q"):
                break

        if ans == "q":
            break
        if ans == "s":
            continue

        row["verified_by_human"] = True
        row["human_verdict"] = {"y": "confirmed", "n": "wrong", "e": "edited"}[ans]

    # write back by (repo, number) so skipped rows are untouched
    index = {(r["repo"], r["number"]): r for r in todo}
    merged = [index.get((r["repo"], r["number"]), r) for r in rows]
    save(merged)
    report(merged)


if __name__ == "__main__":
    main()
