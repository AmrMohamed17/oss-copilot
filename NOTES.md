# OSS Contribution Copilot — Working Note

**Updated:** 2026-08-02 · **Phases 0–2 CLOSED · Phase 3 next** · Repos: `oss-copilot`, `oss-issues-mcp`

---

## 1. What this project is

A supervised multi-agent system that watches OSS repos, judges whether each new issue is
**actionable**, filters to what's **claimable**, surfaces a daily digest, and drafts a **gated**
"I'd like to take this" comment. I use it to find and land real OSS contributions.

**Pipeline:** watch → normalise → classify type (fallback) → **judge reproduction-readiness**
→ deterministic gates → digest → **human approval** → claim comment.

**Two layers:** Layer A = objective core (readiness judge + classifier). Layer B (personalised
ranking) was CUT — no reliable answer key; deferred to behavioural logging.

**Iron rules:** every component is [ARCH]/[MEASURED]/[LEARN] · a component that loses its
justification gets cut · applications never pause for this project.

---

## 2. Phase status

| Phase | What | Status |
|---|---|---|
| 0 | Data & ground-truth foundation | **CLOSED** |
| 1 | MCP domain server (PyPI + Registry) | **CLOSED** |
| 2 | Single-agent readiness baseline | **CLOSED** |
| 3 | LangGraph multi-agent core — [MEASURED] vs Phase 2 | **← NEXT** |
| 4 | Deterministic gates + daily digest + claim/skip logging | |
| 5 | HITL gate + claim drafting (write-scoped token introduced here) | |
| 6 | Self-correction loop — [MEASURED], cut if no lift | |
| 7 | Evals deep + CI gate; test set + MLflow transfer run ONCE | |
| 8 | Cost (model router) + safety (prompt-injection scanning) | |
| 9 | Package + dogfood — README, demo, first real PRs | |

---

## 3. Environment

- Repos: `oss-copilot` (main), `oss-issues-mcp` (published server). Public, MIT.
- Python 3.12 via `uv`. **Always run scripts with `uv run python ...`** (conda `base` shadows the
  venv otherwise — caused an OpenAI import error in Phase 2).
- Postgres via Docker (plain `postgres:17`; pgvector dropped with Layer B), host port 5433.
- Keys in `.env`: `GITHUB_TOKEN` (read-only), `DEEPSEEK_API_KEY`.

---

## 4. Phase 0 — findings (README + LinkedIn material)

- **Labels are author self-reports, not maintainer judgement.** 90.7% of first type labels applied
  by the issue author, 92.1% within 2 min (templates). 29% never labelled. → classifier demoted to
  fallback for the unlabelled 29%.
- **Duplicate detection CUT** — 19/2568 = 0.7% duplicate rate.
- **Reproduction-readiness has real ground truth** — needs-info labels are 100% non-author. Built a
  5-ecosystem calibration corpus (pandas, kubernetes, angular, ray, gradio). MLflow's 40 sealed as
  transfer test.
- **39.3-pt author confound found + fixed** — v1 calibration set: actionable 51.3% insider vs
  needs_info 12.0%. A judge could score on writing style. v2 restricts both classes to
  `author_association=NONE`. v1 kept as `*_v1_confounded.jsonl` (evidence).

## 5. Phase 1 — MCP server (`oss-issues-mcp`, live)

- Published to PyPI + official MCP Registry (`io.github.AmrMohamed17/oss-issues-mcp`, v0.1.1, active).
- Four **derived** tools (not a passthrough): `get_actionable_issue`, `list_new_issues`,
  `get_claim_status` (assignees + linked PRs; comment-scan deferred), `get_repo_context`.
- Security: repo allowlist, read-only, no write tools until Phase 5 gate exists, untrusted-input
  posture. 10 offline unit tests. Three-file split (github/normalize/server) = pure-function logic
  testable without network.

## 6. Phase 2 — single-agent baseline (CLOSED)

- **The arbiter.** One DeepSeek call (`deepseek-chat`, temp 0, JSON out) + versioned rubric.
  Files: `src/oss_copilot/readiness/{rubric,judge}.py`, `scripts/run_baseline.py`.
- **Result (rubric v1, calibration_dev n=360): 69.4% agreement.** needs_info P=0.79 / R=0.53 /
  F1=0.63. Per-ecosystem 54–78% (kubernetes weakest, 54%). Cached in `data/results/baseline_v1.jsonl`.
- Rubric bakes in the "bar shifts by issue type" rule (bug needs repro; design/UX judged on clarity).
- **69.4% is a SUPPRESSED floor.** Reading disagreements: a meaningful share are label-construction
  noise (complete bug reports carrying needs_info from the closed-completed vs needs-info-labelled
  split) + content-free junk. **Not fixed deliberately** — the baseline's only job is to be the
  reference Phase 3 beats on the identical set; a higher floor just shrinks the lift. Considered
  filtering `state_reason=not_planned` but the field wasn't captured in the frozen fixtures, and
  re-fetching would break the freeze — not worth it.
- Rubric locked at v1. calibration_test (240) + MLflow (40) remain SEALED until Phase 7.

---

## 7. Design decisions locked

| Decision | Status | Reason |
|---|---|---|
| Duplicate detection | CUT | 0.7% duplicate rate |
| Type classifier | DEMOTED | fallback for unlabelled 29% |
| Reproduction-readiness | PROMOTED | only signal with real maintainer judgement |
| Layer B ranking | CUT | no reliable answer key; deferred to behavioural logging |
| pgvector | CUT | lost its last job with Layer B |
| PII redaction | CUT | issues rarely contain PII |
| "invalid" third verdict | NOT ADDED | close-reason filtering would handle junk; kept judge 2-way for simplicity |
| Deterministic gates | Phase 4 | metadata beats LLM inference |

---

## 8. Known limitations (README)

1. Calibration set 50/50 by construction; real needs_info prevalence ~3% → agreement ≠ deployment precision.
2. Calibrated on 5 external repos, applied to 5 watched repos; MLflow (40) is the transfer check.
3. Classifier evaluated on labelled, deployed on unlabelled → F1 optimistic.
4. Calibration bodies are current (post-edit) versions; some positives may look complete after edits.
5. Baseline suppressed by label-construction noise (see §6).

---

## 9. Metrics I'll be able to claim

- **Anchor:** multi-agent lifted readiness agreement from **69.4%** → Y% over the single-agent
  baseline (identical dev set). ← Phase 3 produces Y.
- readiness agreement across 5 ecosystems + MLflow transfer (Phase 7)
- tool-call accuracy · routing accuracy · loop rate · recovery rate (Phase 3+)
- classifier macro-F1 / weighted F1 vs author-declared labels (caveated)
- injection catch rate (Phase 8) · CI regressions caught (Phase 7)
- **Payoff:** issues surfaced → PRs opened → PRs merged
- **Null results (assets):** dedupe cut · label-source finding · 39.3-pt confound · Layer B cut

---

## 10. Visibility (done)

- Resume rebuilt: MCP server + findings, no indefensible numbers, Elevvo without metrics.
- LinkedIn synced: headline (agents+MCP), About, Experience, OSS project card.
- Portfolio: OSS case study live at amr-mohammed.com/oss-copilot; BeanBuddy removed; Elevvo fixed.
- LinkedIn posts: #1 label-source finding (live); #2 MCP server (drafted/posting).
- **Resume/portfolio consistent across all four surfaces.**

---

## 11. Phase 3 — what's next

Build the LangGraph multi-agent core for Layer A and measure it against the 69.4% baseline on the
**same calibration_dev set**. The lift (or lack of it) is [MEASURED]: if the multi-agent version
doesn't beat single-agent by a real margin, collapse it and document that. Supervisor/worker
topology, durable Postgres-checkpointed state, routing in deterministic Python, iteration capped
in code. Test set stays sealed.
