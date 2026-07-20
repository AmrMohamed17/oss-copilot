#!/usr/bin/env python3
"""
build_relevance_set.py -- answer key for LAYER B (personal fit ranking).

The only dataset where I am the ground truth. Nobody else can label
"would I take this".

SOURCE: OPEN issues from the five WATCHED repos (langfuse, mlflow, llama_index,
ragas, deepeval) -- the same stream Layer B ranks in production. NOT the
calibration repos, which are a data source only.

GRADED, not binary:
    2 = would take this now
    1 = appealing but not now (too hard, or adjacent to my skills)
    0 = would not take
Graded labels enable NDCG. The middle grade matters: an issue I'd take in three
months is genuinely different from one I'd never touch.

JUDGE INTEREST *AND* FEASIBILITY. A Ray-internals issue can be topically perfect
and practically impossible as a first contribution. The ranker must learn both.

METHOD NOTES (README)
  - Label in ONE sitting where possible; criteria drift across days and drift is
    unmeasurable noise.
  - Re-label a 15-issue subset a week later -> self-consistency %. That number is
    what makes a self-labelled metric credible instead of hand-wavy, and it is
    the CEILING on ranking performance.

Usage:
    python scripts/build_relevance_set.py --build      # sample the issues
    python scripts/build_relevance_set.py              # label them
    python scripts/build_relevance_set.py --recheck    # self-consistency pass
    python scripts/build_relevance_set.py --report
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

RAW = Path("data/raw")
FIXTURES = Path("data/fixtures")
OUT = FIXTURES / "relevance_v1.jsonl"
WATCHED = {"langfuse/langfuse", "mlflow/mlflow", "run-llama/llama_index",
           "vibrantlabsai/ragas", "confident-ai/deepeval"}
TARGET = 60
BODY_CHARS = 1200
random.seed(42)

CONTRIB_HINTS = ["good first issue", "good-first-issue", "help wanted", "help-wanted"]


def build() -> None:
    pool = []
    for path in sorted(RAW.glob("*.jsonl")):
        repo = path.stem.replace("__", "/")
        if repo not in WATCHED:
            continue
        for line in path.open():
            i = json.loads(line)
            if i["state"] != "open":
                continue                       # only issues I could actually claim
            body = (i.get("body") or "").strip()
            if len(body) < 50:
                continue
            pool.append({
                "repo": repo,
                "number": i["number"],
                "title": i["title"],
                "body": body[:6000],
                "labels": i["labels"],
                "contrib_flag": any(any(h in l.lower() for h in CONTRIB_HINTS)
                                    for l in i["labels"]),
                "comments": i.get("comments", 0),
                "created_at": i["created_at"],
                "html_url": i["html_url"],
                "grade": None,
                "reason": "",
                "recheck_grade": None,
            })

    if not pool:
        raise SystemExit("No open issues found. Run fetch_issues.py first.")

    # Spread across repos so one busy repo doesn't dominate the set.
    by_repo: dict[str, list] = {}
    for r in pool:
        by_repo.setdefault(r["repo"], []).append(r)
    per_repo = max(1, TARGET // len(by_repo))

    selected = []
    for repo, rows in by_repo.items():
        # guarantee a few contributable-flagged issues if any exist
        flagged = [r for r in rows if r["contrib_flag"]]
        rest = [r for r in rows if not r["contrib_flag"]]
        n_flag = min(len(flagged), max(1, per_repo // 4))
        selected.extend(random.sample(flagged, n_flag))
        selected.extend(random.sample(rest, min(len(rest), per_repo - n_flag)))

    random.shuffle(selected)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for r in selected:
            f.write(json.dumps(r) + "\n")

    print(f"{OUT}: {len(selected)} open issues")
    for repo, c in Counter(r["repo"] for r in selected).most_common():
        print(f"  {repo:26s} {c}")
    print(f"  contributable-flagged: {sum(1 for r in selected if r['contrib_flag'])}")
    print("\nNow run:  python scripts/build_relevance_set.py")


def load() -> list[dict]:
    return [json.loads(l) for l in OUT.open()]


def save(rows: list[dict]) -> None:
    with OUT.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def show(row: dict, idx: int, total: int) -> None:
    flag = "  [CONTRIBUTABLE-FLAGGED]" if row["contrib_flag"] else ""
    print("\n" + "=" * 72)
    print(f"[{idx}/{total}]  {row['repo']}  #{row['number']}{flag}")
    print(f"labels: {', '.join(row['labels']) or '(none)'}   comments: {row['comments']}")
    print("=" * 72)
    print(f"TITLE: {row['title']}\n")
    print(row["body"][:BODY_CHARS])
    if len(row["body"]) > BODY_CHARS:
        print(f"\n... [{len(row['body']) - BODY_CHARS} more chars]")
    print(f"\n{row['html_url']}")


def label(recheck: bool = False) -> None:
    rows = load()
    field = "recheck_grade" if recheck else "grade"

    if recheck:
        done = [r for r in rows if r["grade"] is not None]
        random.shuffle(done)
        todo = done[:15]
        print("SELF-CONSISTENCY PASS -- 15 issues you already graded.")
        print("Do NOT look at your earlier grade. Judge fresh.\n")
    else:
        todo = [r for r in rows if r["grade"] is None]
        print("Grade each issue:  would I take this?")
        print("  [2] would take this now")
        print("  [1] appealing, but not now (too hard / adjacent)")
        print("  [0] would not take")
        print("  [s] skip   [q] save and quit")
        print("\nJudge INTEREST *and* FEASIBILITY as a first contribution.\n")

    for idx, row in enumerate(todo, 1):
        show(row, idx, len(todo))
        while True:
            ans = input("  [2/1/0/s/q] > ").strip().lower()
            if ans in ("2", "1", "0", "s", "q"):
                break
        if ans == "q":
            break
        if ans == "s":
            continue
        row[field] = int(ans)
        if not recheck:
            row["reason"] = input("  one-line why > ").strip()

    index = {(r["repo"], r["number"]): r for r in todo}
    save([index.get((r["repo"], r["number"]), r) for r in rows])
    report()


def report() -> None:
    rows = load()
    graded = [r for r in rows if r["grade"] is not None]
    print(f"\n{'=' * 58}\nRELEVANCE SET\n{'=' * 58}")
    print(f"  graded: {len(graded)}/{len(rows)}")
    if not graded:
        return
    dist = Counter(r["grade"] for r in graded)
    for g in (2, 1, 0):
        print(f"    grade {g}: {dist[g]:3d}  ({100*dist[g]/len(graded):5.1f}%)")

    rechecked = [r for r in graded if r["recheck_grade"] is not None]
    if rechecked:
        exact = sum(1 for r in rechecked if r["grade"] == r["recheck_grade"])
        binary = sum(1 for r in rechecked
                     if (r["grade"] == 2) == (r["recheck_grade"] == 2))
        n = len(rechecked)
        print(f"\n  SELF-CONSISTENCY (n={n})")
        print(f"    exact grade match : {exact}/{n}  ({100*exact/n:.0f}%)")
        print(f"    binary (take/not) : {binary}/{n}  ({100*binary/n:.0f}%)")
        print("\n  README line:")
        print(f'  "Relevance labels are self-assigned. Self-consistency on a')
        print(f'   {n}-issue re-label after one week was {100*binary/n:.0f}% (binary).')
        print('   Ranking metrics are reported against that ceiling."')
    else:
        print("\n  No self-consistency pass yet. After ~1 week:")
        print("    python scripts/build_relevance_set.py --recheck")

    if dist[2] < 8:
        print(f"\n  WARNING: only {dist[2]} grade-2 issues. precision@k needs enough")
        print("  positives to be meaningful -- consider sampling more.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--recheck", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    if args.build:
        build()
    elif args.report:
        report()
    else:
        label(recheck=args.recheck)


if __name__ == "__main__":
    main()
