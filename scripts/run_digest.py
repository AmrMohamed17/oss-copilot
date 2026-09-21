#!/usr/bin/env python3
"""Produce today's OSS contribution digest.

    uv run python scripts/run_digest.py               # normal daily run
    uv run python scripts/run_digest.py --dry-run     # don't cache/mark (safe re-run)
    uv run python scripts/run_digest.py --limit 15    # cap issues (cheap test)
"""
import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, "src")
from oss_copilot.watcher.pipeline import build_digest
from oss_copilot.watcher.digest import render


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--max-age", type=int, default=120)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    items, stats = await build_digest(a.days, a.max_age, a.limit, a.dry_run)
    out = render(items, stats)
    print("\n" + out)

    if not a.dry_run:
        d = Path("data/digests"); d.mkdir(parents=True, exist_ok=True)
        p = d / f"{date.today().isoformat()}.md"
        p.write_text(out)
        print(f"\nsaved -> {p}")


if __name__ == "__main__":
    asyncio.run(main())