#!/usr/bin/env python3
"""
census_needsinfo.py -- find a CALIBRATION CORPUS.

Reproduction-readiness needs an answer key written by humans. The only such
signal found so far is the needs-info label: MLflow's was 100% applied by
non-authors (real maintainer judgement, zero template contamination), but only
40 examples over 3 years -- short of the ~50 needed.

Calibration repos are a DATA SOURCE, not contribution targets. They do not have
to be projects you use or would send PRs to. That frees selection entirely:
pick whichever projects have the densest maintainer triage culture.

Cheap by design -- 2-3 calls per repo instead of a full pull:
  1. GET /repos/{repo}/labels        -> discover this repo's needs-info vocabulary
  2. GET /search/issues?q=...        -> total_count for each matching label

Search API is limited to ~30 requests/minute, so requests are throttled.

Usage:
    python scripts/census_needsinfo.py                  # built-in candidates
    python scripts/census_needsinfo.py owner/repo ...
"""

import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
API = "https://api.github.com"
SEARCH_DELAY = 2.2          # stay under ~30 search requests/minute
MIN_VIABLE = 50

# Loose patterns -- we are DISCOVERING vocabularies here, not mapping known ones.
# Every hit is printed so you can reject false positives by eye.
NEEDS_INFO_PATTERNS = [
    "needs info", "needs-info", "need info", "more info", "more information",
    "needs more", "awaiting response", "awaiting-response", "author feedback",
    "needs repro", "needs-repro", "reproduction", "reproducible",
    "information-needed", "information needed", "waiting for", "pending response",
    "insufficient", "cannot reproduce", "unable to reproduce", "needs details",
]

# Candidates chosen for TRIAGE DISCIPLINE, not for relevance to your stack.
# Mature projects with dedicated triage teams label needs-info aggressively.
CANDIDATES = [
    # Very large, formal triage processes
    "microsoft/vscode", "flutter/flutter", "kubernetes/kubernetes",
    "rust-lang/rust", "nodejs/node", "electron/electron",
    "facebook/react", "angular/angular", "vuejs/core",
    # Scientific / data Python -- closer to your domain
    "pandas-dev/pandas", "scikit-learn/scikit-learn", "numpy/numpy",
    "pytorch/pytorch", "huggingface/transformers",
    # ML platform / MLOps -- closest to your positioning
    "ray-project/ray", "apache/airflow", "dbt-labs/dbt-core",
    "streamlit/streamlit", "gradio-app/gradio", "wandb/wandb",
    "bentoml/BentoML", "kedro-org/kedro", "PrefectHQ/prefect",
    # Vector / RAG infrastructure
    "chroma-core/chroma", "qdrant/qdrant", "weaviate/weaviate",
]


def headers() -> dict:
    if not TOKEN:
        sys.exit("ERROR: GITHUB_TOKEN missing.")
    return {"Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def find_labels(client: httpx.Client, repo: str) -> list[str]:
    """List the repo's labels and keep those that look like needs-info."""
    hits = []
    for page in (1, 2, 3):
        r = client.get(f"{API}/repos/{repo}/labels",
                       params={"per_page": 100, "page": page},
                       headers=headers(), timeout=30)
        if r.status_code != 200:
            return hits
        batch = r.json()
        if not batch:
            break
        for lab in batch:
            low = lab["name"].lower()
            if any(p in low for p in NEEDS_INFO_PATTERNS):
                hits.append(lab["name"])
    return hits


def count_issues(client: httpx.Client, repo: str, label: str) -> int | None:
    """total_count of issues (not PRs) carrying this label."""
    q = f'repo:{repo} is:issue label:"{label}"'
    r = client.get(f"{API}/search/issues", params={"q": q, "per_page": 1},
                   headers=headers(), timeout=30)
    time.sleep(SEARCH_DELAY)
    if r.status_code == 403:
        print("    (search rate limited -- pausing 60s)")
        time.sleep(60)
        return None
    if r.status_code != 200:
        return None
    return r.json().get("total_count")


def main() -> None:
    repos = sys.argv[1:] or CANDIDATES
    results: list[tuple[str, int, list[str]]] = []

    with httpx.Client(follow_redirects=True) as client:
        for idx, repo in enumerate(repos, 1):
            print(f"[{idx}/{len(repos)}] {repo}")
            labels = find_labels(client, repo)
            if not labels:
                print("    no needs-info style label found")
                results.append((repo, 0, []))
                continue

            total = 0
            detail = []
            for lab in labels[:4]:          # cap: some repos have many variants
                c = count_issues(client, repo, lab)
                if c is None:
                    continue
                total += c
                detail.append(f"{lab} ({c})")
                print(f"    {c:6d}  {lab}")
            results.append((repo, total, detail))

    print(f"\n\n{'=' * 66}\nRANKED BY NEEDS-INFO VOLUME\n{'=' * 66}")
    for repo, total, detail in sorted(results, key=lambda x: -x[1]):
        flag = "VIABLE" if total >= MIN_VIABLE else "thin  "
        print(f"  {flag}  {total:7d}  {repo}")
        if detail:
            print(f"            {', '.join(detail)}")

    viable = [r for r in results if r[1] >= MIN_VIABLE]
    print(f"\n  {len(viable)} of {len(results)} repos clear the {MIN_VIABLE}-example bar.")
    print("\n  NEXT: pick 4-6 from the top, ideally spanning different ecosystems")
    print("  (a JS project, a scientific-Python project, an MLOps project...).")
    print("  Diversity matters more than raw volume: a judge that agrees with")
    print("  maintainers across DIFFERENT cultures generalises. One that agrees")
    print("  with a single repo has only learned that repo's house style.")
    print("\n  CAUTION: counts include closed/stale issues and the label patterns")
    print("  are loose. Eyeball the label names above before trusting a repo.")


if __name__ == "__main__":
    main()
