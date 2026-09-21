import sys; sys.path.insert(0, "src")
from datetime import datetime, timezone, timedelta
from oss_copilot.watcher.gates import evaluate

def _iss(labels=None, created=None):
    return {"labels": labels or [],
            "created_at": created or datetime.now(timezone.utc).isoformat()}

def test_passes_clean_actionable_unclaimed():
    r = evaluate(_iss(), {"claimed": False}, "actionable")
    assert r.passed and not r.reasons

def test_fails_when_not_actionable():
    r = evaluate(_iss(), {"claimed": False}, "needs_info")
    assert not r.passed and "not actionable" in r.reasons

def test_fails_when_claimed():
    r = evaluate(_iss(), {"claimed": True}, "actionable")
    assert not r.passed and "already claimed" in r.reasons

def test_fails_when_blocked_label():
    r = evaluate(_iss(labels=["needs-info"]), {"claimed": False}, "actionable")
    assert not r.passed

def test_fails_when_stale():
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    r = evaluate(_iss(created=old), {"claimed": False}, "actionable", max_age_days=120)
    assert not r.passed and any("stale" in x for x in r.reasons)

def test_gfi_is_signal_not_gate():
    r = evaluate(_iss(labels=["good first issue"]), {"claimed": False}, "actionable")
    assert r.passed and "good first issue" in r.signals