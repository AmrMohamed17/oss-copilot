#!/usr/bin/env python3
"""
build_golden_set.py -- answer key for the TYPE CLASSIFIER (Layer A, fallback path).

CONTEXT
  The classifier is a demoted component. 71% of issues arrive with a type label
  already attached (author picked a template), so at runtime the classifier only
  handles the 29% that never get labelled. Effort here is scaled accordingly.

GROUND TRUTH
  Author-declared labels (90.7% applied by the issue author at creation via
  templates). NOT maintainer judgement. Measured noise: ~5.3% genuine
  recategorisation by maintainers -- that is the error estimate; no
  hand-verification pass is run.

BUILT FROM CACHED DATA -- no API calls. Labels already exist.

LIMITATION (README)
  Evaluated on LABELLED issues; deployed on UNLABELLED ones. Those populations
  differ -- unlabelled issues come from people who bypassed the template, filed
  via API, or hit a repo with no template. Measured F1 is therefore an
  OPTIMISTIC estimate of real fallback performance.

SPLITS: 100 dev / 50 test. Test untouched until Phase 2.

Usage:
    python scripts/build_golden_set.py
    python scripts/build_golden_set.py --size 150
"""

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import yaml

RAW = Path("data/raw")
FIXTURES = Path("data/fixtures")
TAXONOMY = Path("data/taxonomy/v1.yaml")
GROUND_TRUTH_REPOS = {
    "langfuse/langfuse", "mlflow/mlflow",
    "run-llama/llama_index", "vibrantlabsai/ragas",
}
random.seed(42)

SHORT_BODY = 200      # "terse issue" hard case
LONG_BODY = 4000      # "wall of logs" hard case


def canonical_types(repo: str, labels: list[str], tax: dict) -> list[str]:
    block = tax["repos"].get(repo, {})
    found = []
    for canonical in tax["canonical_types"]:
        names = [n.lower() for n in block.get(canonical, []) or []]
        if any(l.lower() in names for l in labels):
            found.append(canonical)
    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=150)
    args = ap.parse_args()

    tax = yaml.safe_load(TAXONOMY.read_text())
    FIXTURES.mkdir(parents=True, exist_ok=True)

    pool: list[dict] = []
    for path in sorted(RAW.glob("*.jsonl")):
        repo = path.stem.replace("__", "/")
        if repo not in GROUND_TRUTH_REPOS:
            continue
        for line in path.open():
            issue = json.loads(line)
            types = canonical_types(repo, issue["labels"], tax)
            if not types:
                continue                       # no ground truth -> not usable
            body = issue.get("body") or ""
            if len(body.strip()) < 30:
                continue
            pool.append({
                "repo": repo,
                "number": issue["number"],
                "title": issue["title"],
                "body": body[:8000],
                "types": types,                       # multi-label preserved
                "primary_type": types[0],
                "multi_label": len(types) > 1,
                "raw_labels": issue["labels"],
                "state": issue["state"],
                "created_at": issue["created_at"],
                "html_url": issue["html_url"],
                "hard_case": (len(types) > 1
                              or len(body) < SHORT_BODY
                              or len(body) > LONG_BODY),
            })

    if not pool:
        raise SystemExit("Empty pool -- run fetch_issues.py first.")

    print(f"pool: {len(pool)} labelled issues from {len(GROUND_TRUTH_REPOS)} repos")
    dist = Counter(r["primary_type"] for r in pool)
    print("natural distribution:")
    for t, c in dist.most_common():
        print(f"  {t:14s} {c:5d}  ({100*c/len(pool):5.1f}%)")

    # Stratified sample: even quota per type, since rare classes (documentation,
    # question) would be almost absent from a random sample of a bug-heavy pool.
    by_type: dict[str, list] = defaultdict(list)
    for r in pool:
        by_type[r["primary_type"]].append(r)

    types = [t for t in tax["canonical_types"] if by_type[t]]
    quota = args.size // len(types)
    selected: list[dict] = []
    for t in types:
        bucket = by_type[t]
        # bias toward hard cases: an easy-only set produces fake-high F1
        hard = [r for r in bucket if r["hard_case"]]
        easy = [r for r in bucket if not r["hard_case"]]
        n_hard = min(len(hard), quota // 3)
        n_easy = min(len(easy), quota - n_hard)
        selected.extend(random.sample(hard, n_hard))
        selected.extend(random.sample(easy, n_easy))

    random.shuffle(selected)

    # split per type so both halves keep the same class balance
    buckets: dict[str, list] = defaultdict(list)
    for r in selected:
        buckets[r["primary_type"]].append(r)
    dev, test = [], []
    for bucket in buckets.values():
        cut = int(len(bucket) * 0.67)
        dev.extend(bucket[:cut])
        test.extend(bucket[cut:])

    for name, data in (("golden_dev", dev), ("golden_test", test)):
        path = FIXTURES / f"{name}.jsonl"
        with path.open("w") as f:
            for r in data:
                f.write(json.dumps(r) + "\n")
        c = Counter(r["primary_type"] for r in data)
        hard = sum(1 for r in data if r["hard_case"])
        print(f"\n{path}: {len(data)} rows ({hard} hard cases)")
        for t, n in c.most_common():
            print(f"    {t:14s} {n}")

    print(f"\n{'=' * 58}")
    print("  README notes for this set:")
    print("  - Ground truth is AUTHOR-DECLARED (90.7% author-applied via")
    print("    templates), not maintainer judgement. Estimated label noise")
    print("    ~5.3% (measured recategorisation rate).")
    print("  - Evaluated on labelled issues, deployed on unlabelled ones ->")
    print("    reported F1 is an OPTIMISTIC estimate of fallback performance.")
    print("  - golden_test.jsonl is untouched until Phase 2.")


if __name__ == "__main__":
    main()
