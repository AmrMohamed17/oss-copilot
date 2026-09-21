"""Deterministic gates — pure Python, no LLM. This is what replaced the cut
Layer B: filter the readiness-judged stream down to issues worth surfacing,
using facts GitHub states outright rather than model inference.

Pure functions on dicts, so they unit-test offline with no network — same
discipline as the MCP server's normalize/claim logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

GFI = ("good first issue", "good-first-issue")
HELP = ("help wanted", "help-wanted", "contributions welcome")
BLOCK = ("needs info", "needs-info", "blocked", "awaiting response",
         "needs author feedback", "information-needed")


@dataclass
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)   # why it was filtered out
    signals: list[str] = field(default_factory=list)   # positive highlights for ranking


def _has(labels: list[str], needles) -> bool:
    low = [l.lower() for l in labels]
    return any(any(n in l for n in needles) for l in low)


def evaluate(issue: dict, claim: dict, readiness_verdict: str,
             max_age_days: int = 120) -> GateResult:
    """Hard gates decide pass/fail. Signals only inform ranking, never exclude
    — good-first-issue is rare, so gating on it would empty the digest."""
    reasons, signals = [], []
    labels = issue.get("labels", [])

    # --- hard gates ---
    if readiness_verdict != "actionable":
        reasons.append("not actionable")
    if claim.get("claimed"):
        reasons.append("already claimed")
    if _has(labels, BLOCK):
        reasons.append("blocked / needs-info label")
    created = issue.get("created_at")
    if created:
        try:
            age = (datetime.now(timezone.utc)
                   - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
            if age > max_age_days:
                reasons.append(f"stale ({age}d old)")
        except ValueError:
            pass

    # --- signals (highlight, don't filter) ---
    if _has(labels, GFI):
        signals.append("good first issue")
    if _has(labels, HELP):
        signals.append("help wanted")

    return GateResult(passed=not reasons, reasons=reasons, signals=signals)