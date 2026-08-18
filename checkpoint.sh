#!/usr/bin/env bash
# Pre-Phase-4 checkpoint. Run from the oss-copilot repo root.
# Read-only — verifies state, changes nothing.

set -u
PASS=0; WARN=0; FAIL=0
ok(){ echo "  ✅ $1"; PASS=$((PASS+1)); }
warn(){ echo "  ⚠️  $1"; WARN=$((WARN+1)); }
no(){ echo "  ❌ $1"; FAIL=$((FAIL+1)); }
hr(){ echo; echo "── $1 ──"; }

hr "1. Repo state"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 && ok "in a git repo" || no "not a git repo — wrong directory?"
BR=$(git branch --show-current 2>/dev/null); echo "  branch: $BR"
if [ -z "$(git status --porcelain 2>/dev/null)" ]; then ok "working tree clean"
else warn "uncommitted changes present:"; git status --short | sed 's/^/       /'; fi
UNPUSHED=$(git log @{u}.. --oneline 2>/dev/null | wc -l)
[ "$UNPUSHED" = "0" ] && ok "all commits pushed" || warn "$UNPUSHED commit(s) not pushed"
echo "  last 3 commits:"; git log --oneline -3 2>/dev/null | sed 's/^/       /'

hr "2. Phase 0 — frozen fixtures present"
for f in calibration_dev calibration_test golden_dev golden_test; do
  p="data/fixtures/$f.jsonl"
  [ -f "$p" ] && ok "$f.jsonl ($(wc -l <"$p" | tr -d ' ') rows)" || no "$p MISSING"
done
for f in calibration_dev_v1_confounded calibration_test_v1_confounded; do
  [ -f "data/fixtures/$f.jsonl" ] && ok "$f.jsonl (confound evidence kept)" || warn "$f.jsonl missing"
done
[ -f data/taxonomy/v1.yaml ] && ok "taxonomy v1.yaml present" || warn "taxonomy missing"

hr "3. Phase 2/3 — readiness code + results"
for f in src/oss_copilot/readiness/rubric.py src/oss_copilot/readiness/judge.py \
         src/oss_copilot/readiness/graph.py src/oss_copilot/readiness/type_rubrics.py; do
  [ -f "$f" ] && ok "$(basename $f)" || no "$f MISSING"
done
[ -f data/results/baseline_v1.jsonl ] && ok "baseline_v1 results ($(wc -l <data/results/baseline_v1.jsonl|tr -d ' ') rows)" || no "baseline results MISSING"
ls data/results/multiagent_v*.jsonl >/dev/null 2>&1 && ok "multi-agent results present (null-result evidence)" || warn "multi-agent results missing"

hr "4. Test seal intact (must NOT have been scored)"
# the sealed sets should have NO corresponding results file
if ls data/results/*test* >/dev/null 2>&1; then no "a *test* results file exists — seal may be broken!"; else ok "no test-set results — seal intact"; fi

hr "5. Environment"
[ -f .env ] && ok ".env present" || no ".env MISSING (need GITHUB_TOKEN, DEEPSEEK_API_KEY)"
if [ -f .env ]; then
  grep -q GITHUB_TOKEN .env && ok "GITHUB_TOKEN in .env" || no "GITHUB_TOKEN missing from .env"
  grep -q DEEPSEEK_API_KEY .env && ok "DEEPSEEK_API_KEY in .env" || no "DEEPSEEK_API_KEY missing"
fi
git ls-files --error-unmatch .env >/dev/null 2>&1 && no ".env is TRACKED — rotate tokens!" || ok ".env not tracked"
uv run python -c "import langgraph, openai, httpx" 2>/dev/null && ok "core deps import (langgraph, openai, httpx)" || warn "some deps don't import — run: uv sync"

hr "6. Database"
if docker compose ps 2>/dev/null | grep -qi healthy; then ok "postgres container healthy"
elif docker compose ps 2>/dev/null | grep -qi "up"; then warn "container up but not 'healthy' yet"
else warn "postgres not running (docker compose up -d) — needed for Phase 4 state"; fi

hr "7. MCP server (separate repo) — live check"
VER=$(curl -s https://pypi.org/pypi/oss-issues-mcp/json 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['info']['version'])" 2>/dev/null)
[ -n "$VER" ] && ok "oss-issues-mcp live on PyPI (v$VER)" || warn "couldn't reach PyPI (offline?)"

hr "8. The readiness judge still works end-to-end"
echo "  (one live API call — confirms the core component is functional)"
uv run python -c "
import sys; sys.path.insert(0,'src')
from oss_copilot.readiness.judge import judge_issue
r = judge_issue('App crashes on startup', 'It just crashes. No idea why.')
print('  judge returned:', r.get('verdict') or r.get('error'))
" 2>&1 | sed 's/^/  /'

echo; echo "════════════════════════════════"
echo "  PASS: $PASS   WARN: $WARN   FAIL: $FAIL"
[ "$FAIL" = "0" ] && echo "  Core intact. Warnings are usually environment (docker/venv)." \
                  || echo "  Address ❌ items before Phase 4."
echo "════════════════════════════════"
