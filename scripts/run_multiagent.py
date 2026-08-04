#!/usr/bin/env python3
"""
run_multiagent.py -- Phase 3: measure the LangGraph multi-agent pipeline and
compare it DIRECTLY to the Phase 2 single-agent baseline.

Same dev set, same scoring, same metrics as run_baseline.py -- the ONLY change
is single LLM call -> classify+route+worker graph. That makes the delta clean:
any difference is the architecture, not the measurement.

DISCIPLINE (unchanged):
- calibration_dev only. test set + MLflow 40 stay SEALED.
- results cached; errors NOT cached (re-run retries them).

Usage:
    python scripts/run_multiagent.py --limit 20    # smoke test
    python scripts/run_multiagent.py               # full dev set + compare
    python scripts/run_multiagent.py --score        # re-score cache only
"""
import argparse, json, sys, time
from pathlib import Path

sys.path.insert(0, "src")
from oss_copilot.readiness.graph import judge_issue_multiagent
from oss_copilot.readiness.type_rubrics import RUBRIC_VERSION

DEV = Path("data/fixtures/calibration_dev.jsonl")
CACHE = Path(f"data/results/{RUBRIC_VERSION}.jsonl")
BASELINE = Path("data/results/baseline_v1.jsonl")
GT = {"needs_info": "needs_info", "actionable": "actionable"}


def load_jsonl(p): return [json.loads(l) for l in p.open()] if p.exists() else []
def dev(): return load_jsonl(DEV)


def load_cache():
    return {(r["repo"], r["number"]): r for r in load_jsonl(CACHE)}


def run(limit):
    data = dev()[:limit] if limit else dev()
    cache = load_cache()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    todo = [d for d in data if (d["repo"], d["number"]) not in cache]
    print(f"dev: {len(data)} | cached: {len(data)-len(todo)} | to run: {len(todo)}")
    errors = 0
    with CACHE.open("a") as f:
        for i, iss in enumerate(todo, 1):
            res = judge_issue_multiagent(iss["title"], iss["body"])
            if res.get("error"):        # DON'T cache errors -- retry next run
                errors += 1
                print(f"  {i}/{len(todo)} ERROR {res['error'][:50]}", end="\r")
                continue
            row = {"repo": iss["repo"], "number": iss["number"],
                   "ecosystem": iss["ecosystem"], "ground_truth": iss["label"],
                   "issue_type": res.get("issue_type"),
                   "verdict": res["verdict"], "reason": res.get("reason")}
            f.write(json.dumps(row) + "\n"); f.flush()
            print(f"  {i}/{len(todo)} {iss['repo']}#{iss['number']} "
                  f"[{res.get('issue_type')}] -> {res['verdict']}", end="\r")
            time.sleep(0.3)
    print(f"\ndone. errors this run: {errors}")
    score()


def _metrics(rows):
    n = len(rows)
    correct = sum(1 for r in rows if r["verdict"] == GT[r["ground_truth"]])
    tp = sum(1 for r in rows if r["ground_truth"]=="needs_info" and r["verdict"]=="needs_info")
    fn = sum(1 for r in rows if r["ground_truth"]=="needs_info" and r["verdict"]=="actionable")
    fp = sum(1 for r in rows if r["ground_truth"]=="actionable" and r["verdict"]=="needs_info")
    tn = sum(1 for r in rows if r["ground_truth"]=="actionable" and r["verdict"]=="actionable")
    prec = tp/(tp+fp) if tp+fp else 0
    rec = tp/(tp+fn) if tp+fn else 0
    f1 = 2*prec*rec/(prec+rec) if prec+rec else 0
    return dict(n=n, acc=correct/n if n else 0, correct=correct,
                tp=tp, fn=fn, fp=fp, tn=tn, prec=prec, rec=rec, f1=f1)


def score():
    dev_keys = {(d["repo"], d["number"]) for d in dev()}
    rows = [r for r in load_cache().values() if (r["repo"], r["number"]) in dev_keys]
    if not rows:
        print("no scored rows yet."); return
    m = _metrics(rows)
    print(f"\n{'='*56}\nMULTI-AGENT — {RUBRIC_VERSION}  (dev, n={m['n']})\n{'='*56}")
    print(f"  agreement : {100*m['acc']:.1f}%  ({m['correct']}/{m['n']})")
    print(f"  needs_info  P={m['prec']:.3f}  R={m['rec']:.3f}  F1={m['f1']:.3f}")
    print(f"  confusion:  TP={m['tp']} FN={m['fn']} FP={m['fp']} TN={m['tn']}")

    # per-type breakdown (only the multi-agent has this)
    by_t = {}
    for r in rows: by_t.setdefault(r.get("issue_type","?"), []).append(r)
    print(f"\n  by classified type:")
    for t, rs in sorted(by_t.items()):
        c = sum(1 for r in rs if r["verdict"]==GT[r["ground_truth"]])
        print(f"    {t:14s} n={len(rs):3d}  agreement {100*c/len(rs):.1f}%")

    # ---- THE COMPARISON ----
    base = [r for r in load_jsonl(BASELINE)
            if (r["repo"], r["number"]) in dev_keys and r.get("verdict")]
    if base:
        bm = _metrics(base)
        # compare only on issues BOTH scored, for a fair paired delta
        mk = {(r["repo"], r["number"]) for r in rows}
        bk = {(r["repo"], r["number"]) for r in base}
        common = mk & bk
        rc = _metrics([r for r in rows if (r["repo"],r["number"]) in common])
        bc = _metrics([r for r in base if (r["repo"],r["number"]) in common])
        print(f"\n{'='*56}\n  BASELINE vs MULTI-AGENT  (paired, n={len(common)})\n{'='*56}")
        print(f"                     baseline   multi-agent   delta")
        print(f"    agreement        {100*bc['acc']:5.1f}%      {100*rc['acc']:5.1f}%     "
              f"{100*(rc['acc']-bc['acc']):+5.1f}")
        print(f"    needs_info F1     {bc['f1']:.3f}      {rc['f1']:.3f}     "
              f"{rc['f1']-bc['f1']:+.3f}")
        print(f"    needs_info recall {bc['rec']:.3f}      {rc['rec']:.3f}     "
              f"{rc['rec']-bc['rec']:+.3f}")
        print(f"\n  VERDICT:")
        d = rc['acc'] - bc['acc']
        if d >= 0.05:
            print(f"    Multi-agent wins by {100*d:.1f} pts. It earns its place.")
            print(f"    Anchor metric: agreement {100*bc['acc']:.1f}% -> {100*rc['acc']:.1f}%.")
        elif d <= -0.02:
            print(f"    Multi-agent is WORSE by {100*abs(d):.1f} pts. Investigate the")
            print(f"    classifier (mis-routing?) before concluding.")
        else:
            print(f"    Delta is {100*d:+.1f} pts -- within noise. The decomposition")
            print(f"    did NOT earn its complexity. Honest move: collapse to the")
            print(f"    single agent and document the null result. Extra cost = 2x")
            print(f"    LLM calls/issue for no gain.")
    else:
        print("\n  (no baseline cache found -- run run_baseline.py first to compare)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int); ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    score() if a.score else run(a.limit)


if __name__ == "__main__":
    main()
