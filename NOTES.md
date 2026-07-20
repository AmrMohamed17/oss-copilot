# OSS Contribution Copilot — Working Note

**Updated:** 2026-07-20 · **PHASE 0 CLOSED** · Repo: `AmrMohamed17/oss-copilot`

---

## 1. What this project is (revised)

A supervised multi-agent system that watches OSS repos, judges whether each new issue is
**actionable**, filters to what's **claimable**, surfaces a daily digest, and drafts a **gated**
"I'd like to take this" comment. I use it to find and land real OSS contributions.

**Pipeline:** watch → normalise → classify type (fallback) → **judge reproduction-readiness**
→ deterministic gates → digest → **human approval** → claim comment.

**Layer B (personalised semantic ranking) was CUT.** See §5.7. Replaced by deterministic gates.

**Iron rules:** every component is [ARCH], [MEASURED], or [LEARN] · a component that loses its
justification gets cut · applications never pause for this project.

---

## 2. Environment (done)

| Thing | Value |
|---|---|
| Repo | `oss-copilot`, public, MIT |
| Python | 3.12 via `uv`; httpx, python-dotenv, pyyaml |
| DB | Docker `pgvector/pgvector:pg17`, host port **5433**, pgvector 0.8.5 installed |
| Token | Fine-grained PAT, read-only, 5000 req/hr |

**Note:** pgvector is installed but **no longer used** — its only remaining job (fit-matching)
died with Layer B. Postgres now does relational work only: issue state, LangGraph checkpoints,
seen/unseen tracking. Either drop to plain `postgres:17` or keep the extension idle and say why.

---

## 3. Repo roster (locked)

| Role | Repos |
|---|---|
| **Ground truth** (classifier key) | langfuse, mlflow, llama_index, ragas |
| **Watched** (the stream) | + deepeval |
| **Contribution targets** | ragas, deepeval, mlflow (have open GFI) |
| **Calibration corpus** (readiness key) | pandas, kubernetes, angular, ray, gradio |

**Rejected:** langchain (`external` on 221/226 = routing tag; 0 open GFI) · haystack (priority
culture; 67% labelled but 8% type-clean) · dvc (15 issues/90d) · flutter (`has reproducible
steps` = INVERSE signal) · pytorch (label self-describes as deprecated) · vscode
(`*not-reproducible` = "we tried and failed", different judgement).

---

## 4. Artifacts built

**Fixtures (committed, frozen):**
| File | Contents |
|---|---|
| `calibration_dev.jsonl` | 360 rows (180/180) — readiness judge, dev |
| `calibration_test.jsonl` | 240 rows (120/120) — readiness judge, **sealed until Phase 7** |
| `calibration_*_v1_confounded.jsonl` | v1, kept as evidence of the confound finding |
| `golden_dev.jsonl` | 96 rows, 24 per type — classifier, dev |
| `golden_test.jsonl` | 52 rows, 13 per type — classifier, **sealed until Phase 2** |
| `data/taxonomy/v1.yaml` | v1.0 — 4 canonical types |
| MLflow's 40 needs-info | **sealed** — readiness transfer test |

**Scripts (12):** `probe_repo` · `fetch_issues` · `measure_label_lag` · `measure_label_source` ·
`audit_ground_truth` · `census_needsinfo` · `build_calibration_set` (v1) ·
`build_calibration_set_v2` · `review_calibration` · `check_author_confound` ·
`build_golden_set` · `build_relevance_set` (**built but unused — Layer B cut**)

---

## 5. Findings (all measured — README + LinkedIn material)

### 5.1 Gate A was defined wrong — denominator fix
Type labels / **all** issues → wrong; unlabelled issues have no ground truth to sample.
Corrected to type labels / **labelled** issues. llama_index 98%, langfuse 94%, mlflow 89%,
ragas 100%, haystack 8%. *Fixing a metric definition after seeing data is legitimate; moving a
threshold would not be. The 60% bar never moved.*

### 5.2 "Maintainer ground truth" doesn't exist — labels are author self-reports
- **90.7%** of first type labels applied by the **issue author**; 7.6% maintainer; 1.7% bot
- **92.1%** applied within 2 minutes → GitHub issue templates
- **93.9%** labelled within 1 hour; median lag **0.00 h**
- **29.0%** (744/2568) never receive a type label

→ Classifier **demoted** to fallback for the unlabelled 29%, scored against *author-declared*
labels with the caveat stated.

### 5.3 Duplicate detection CUT
**19 / 2,568 = 0.7%.** Gate B failed. Documented null result.

### 5.4 A broken metric of mine, caught and fixed
`measure_label_source.py` reported 27.4% "corrected later" — it counted *any* later type-label
event, and langfuse's `unconfirmed bug → bug` confirmation workflow inflated it to 93.8%.
Comparing **canonical types**: **5.3%** real recategorisation. Still confounded with maintainer
diligence (ragas 13.3%, llama_index 0.0%).

### 5.5 Reproduction-readiness has real ground truth → Layer A headline
needs-info labels are **100% non-author** — genuine maintainer judgement, zero template
contamination. MLflow alone too thin (40 over 3 years), so a **5-repo calibration corpus** was
built (600 examples). **MLflow's 40 sealed as transfer test.**

### 5.6 A 39.3-point author confound — found and fixed
v1 insider rate: **actionable 51.3%** vs **needs_info 12.0%**. Worst: kubernetes 71.7% vs 13.3%.
A judge could score well by detecting insider writing style (`[Serve]` prefixes, internal jargon,
"Proposed Fix" sections) rather than information sufficiency — shortcut learning that collapses
in deployment, where ~88% of issues are outsider-authored.
**Fix:** v2 restricts **both** classes to `author_association == NONE`. Confirmed 300/300 each.

### 5.7 Layer B cut — narrowed three times, then removed
The personalised ranking layer was progressively redefined:
1. *personal taste* → I have no formed preferences yet (new to OSS)
2. *wantedness* (maintainers want it, unclaimed, unblocked) → **all machine-readable from
   GitHub metadata**; an LLM and a hand-labelled set were both redundant
3. *tractability* (would I land a merge?) → a real judgement, but the answer key would be
   self-labelled by someone without the domain experience to label it reliably

**Decision: cut.** Same standard applied in §5.2 — labels from someone guessing are not ground
truth. Replaced by **deterministic gates** (language filter, unclaimed, wanted, not stale, not
blocked): cheaper, inspectable, no eval required, and better than an LLM inferring facts GitHub
states outright.
**Consequence: pgvector cut** — fit-matching was its last remaining job.
**Deferral is real, not polite:** the digest logs every claim/skip decision from day one. After
~2 months of use that produces a *behavioural* relevance set — strictly better ground truth than
anything hand-labelled today, at zero extra cost.

---

## 6. Known limitations (must appear in README)

1. **Body edits.** GitHub returns the *current* body; an author may have edited theirs to add
   missing details after being asked. Not cheaply detectable via REST.
2. **Class balance.** Calibration set is 50/50 by construction; real needs-info prevalence is
   **~3%**. Measured agreement is **not** deployment precision.
3. **Transfer assumption.** Calibrated on 5 external repos, applied to 5 watched repos. MLflow
   transfer test is the check — one repo, 40 examples.
4. **Classifier distribution shift.** Evaluated on labelled issues, deployed on unlabelled ones.
   Reported F1 is **optimistic**.
5. **Golden set thin classes.** `documentation` had 87 issues in a 2,568 pool; 37 were used.
   Report macro-F1 *and* distribution-weighted F1 — natural split is 64% bug / 3.4% docs.
6. **Truncated pulls.** langfuse/llama_index/ragas hit the 3,000-item ceiling; only mlflow was
   re-pulled at 1,095 days (1,551 issues).
7. **Dev/test difficulty gap.** golden_dev is 32% hard cases, golden_test 21% — a dev/test gap
   may be difficulty, not overfitting.

---

## 7. Design decisions locked

| Decision | Status | Reason |
|---|---|---|
| Duplicate detection | **CUT** | 0.7% duplicate rate |
| Type classifier | **DEMOTED** | fallback for the 29% unlabelled |
| Reproduction-readiness | **PROMOTED** | only signal with real maintainer judgement |
| Layer B semantic ranking | **CUT** | no reliable answer key (§5.7) |
| pgvector | **CUT** | lost its last job with Layer B |
| PII redaction | **CUT** | issues rarely contain PII |
| Deterministic gates | **ADDED** | replaces Layer B; metadata beats inference |
| Claim/skip logging | **ADDED** | builds a behavioural relevance set for later |
| Queue/scheduler | **KEPT** | polling 5 repos on a schedule is real throughput |
| `maintenance` type | **DROPPED** | 7 of 2,575 issues; was a component-tag mapping error |

---

## 8. Phase map

| Phase | What | Status |
|---|---|---|
| **0** | Data & ground-truth foundation | **CLOSED** |
| **1** | MCP domain server (standalone repo, PyPI + Registry) | **← next** |
| 2 | Single-agent baseline — **the arbiter**; golden_test opened | |
| 3 | LangGraph objective core — [MEASURED] vs Phase 2 | |
| 4 | Deterministic gates + daily digest + claim/skip logging | |
| 5 | HITL gate + claim drafting; write-scoped token introduced here | |
| 6 | Self-correction loop — [MEASURED], cut if no lift | |
| 7 | Evals deep + CI gate; calibration_test and MLflow transfer run **once** | |
| 8 | Cost (model router) + safety (prompt-injection scanning) | |
| 9 | Package + dogfood — README, demo, video, first real PRs | |

---

## 9. Metrics I'll be able to claim

**Anchor:** *multi-agent lifted end-to-end success X% → Y% over a single-agent baseline*
(relative — unaffected by label noise)

**Core:**
- readiness agreement vs maintainer judgement, **5 ecosystems** + MLflow transfer result
- tool-call accuracy · routing accuracy · loop rate · recovery rate
- indirect prompt-injection catch rate
- CI regressions caught during development

**Caveated:** classifier macro-F1 + weighted F1 vs author-declared labels, fallback path only

**Payoff:** issues surfaced → **PRs opened** → **PRs merged**

**Null results (assets):** dedupe cut (0.7%) · label-source finding (90.7% author-applied) ·
author confound found+fixed (39.3 pts) · Layer B cut for want of a reliable answer key ·
reflexion lift (pending)

---

## 10. Timing

- **Portfolio:** can add now — in-progress with a build log is an asset
- **Resume:** after Phase 2 (published MCP server = linkable artifact + first real numbers)
- **LinkedIn:** post 1 after README — lead with a finding (§5.2 or §5.6), not an announcement
- **Applications: never paused**

---

## 11. Immediate next steps

1. Write the README properly (findings §5, limitations §6, decisions §7)
2. LinkedIn post 1 — the label-source finding, or the author confound
3. **Phase 1** — MCP domain server
