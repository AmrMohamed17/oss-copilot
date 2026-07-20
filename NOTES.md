# OSS Contribution Copilot — Working Note

**Last updated:** 2026-07-20 · **Phase 0, ~75% complete** · Repo: `AmrMohamed17/oss-copilot`

---

## 1. What this project is

A supervised multi-agent system that watches OSS repos, judges whether each new issue is
**actionable**, ranks the actionable ones against **my** profile, and drafts a **gated**
"I'd like to take this" comment. I use it myself to find real OSS contributions.

**Two layers:**
- **Layer A — objective core.** Reproduction-readiness judgement (headline) + type
  classification (fallback). Measured against external human ground truth.
- **Layer B — personal fit ranking.** pgvector profile matching → daily digest → gated claim.
  Self-labelled metrics, honestly caveated.

**Iron rules:** Layer B never eats Layer A · every component is [ARCH], [MEASURED], or [LEARN]
· applications never pause for this project.

---

## 2. Environment (done)

| Thing | Value |
|---|---|
| Repo | `oss-copilot`, public, MIT |
| Python | 3.12 via `uv`; deps: httpx, python-dotenv, pyyaml |
| DB | Docker `pgvector/pgvector:pg17`, host port **5433** (5432 = DocuMind), pgvector **0.8.5** |
| Token | Fine-grained PAT, read-only, 5000 req/hr confirmed |
| Layout | `scripts/` · `data/{raw,fixtures,taxonomy}` · `src/oss_copilot` · `profile/` |

`.env` gitignored, `.env.example` committed. `data/raw/` gitignored; `data/fixtures/` and
`data/taxonomy/` **committed** (frozen fixtures = deterministic evals).

---

## 3. Repo roster (locked)

**Four roles — these are NOT the same list:**

| Role | Repos | Purpose |
|---|---|---|
| **Ground truth** | langfuse, mlflow, llama_index, ragas | classifier answer key |
| **Watched** | + deepeval | the issue stream |
| **Contribution targets** | ragas, deepeval, mlflow (have open GFI) | where I send PRs |
| **Calibration corpus** | pandas, kubernetes, angular, ray, gradio | readiness judge answer key — pure data source, never contributed to |

**Rejected, with reasons:** langchain (`external` on 221/226 = routing tag not type; 0 open GFI)
· haystack (priority culture — 67% labelled but only 8% type-clean) · dvc (15 issues/90d, too
quiet) · flutter (`has reproducible steps` = the INVERSE signal) · pytorch (label self-describes
as deprecated) · vscode (`*not-reproducible` = "we tried and failed", different judgement).

---

## 4. Scripts written

| Script | Does |
|---|---|
| `probe_repo.py` | repo verification, Gate A verdict, label vocabulary dump |
| `fetch_issues.py` | real pull → `data/raw/*.jsonl`, caches, drops PRs + bots |
| `measure_label_lag.py` | time-to-first-type-label, never-labelled rate |
| `measure_label_source.py` | **who** applied the label (author / bot / maintainer) |
| `audit_ground_truth.py` | duplicate volume, needs-info volume, real type corrections |
| `census_needsinfo.py` | scans 26 repos for needs-info density (labels + search API) |
| `build_calibration_set.py` | v1 calibration set (superseded) |
| `review_calibration.py` | CLI for hand-verifying labels |
| `check_author_confound.py` | enriches `author_association`, tests class separability |
| `build_calibration_set_v2.py` | author-matched rebuild ← **run this next** |

---

## 5. Findings (all measured, all README material)

### 5.1 Gate A was defined wrong — denominator fix
Originally: type labels / **all** issues. Wrong — unlabelled issues have no ground truth to
sample, so they're excluded, not failures. Corrected: type labels / **labelled** issues.
Result: llama_index 98%, langfuse 94%, mlflow 89%, ragas 100%, haystack 8%.
*Fixing a metric definition after seeing data is legitimate; moving a threshold would not be.
The 60% bar never moved.*

### 5.2 "Maintainer ground truth" doesn't exist — labels are author self-reports
- **90.7%** of first type labels applied by the **issue author**; 7.6% maintainer; 1.7% bot
- **92.1%** applied within 2 minutes of creation → GitHub issue templates
- **93.9%** labelled within 1 hour; median lag **0.00 h**
- **29.0%** (744/2568) never receive a type label

→ Classifier **demoted** to a fallback for the unlabelled 29%, scored against
*author-declared* labels with the caveat stated.

### 5.3 Duplicate detection CUT (Gate B failed)
**19 duplicates / 2,568 issues = 0.7%.** Nowhere near the ~50 needed. Documented null result.

### 5.4 A broken metric of mine, caught and fixed
`measure_label_source.py` reported 27.4% "corrected later" — but it counted *any* subsequent
type-label event. Langfuse's `unconfirmed bug → bug` confirmation workflow inflated it to 93.8%.
Comparing **canonical types** instead: **5.3%** real recategorisation. Even that is confounded
with maintainer diligence (ragas 13.3%, llama_index 0.0%) — report with that caveat or not at all.

### 5.5 Reproduction-readiness has real ground truth → promoted to headline
needs-info labels are **100% non-author** (20/20 sampled on mlflow) — genuine maintainer
judgement, zero template contamination. MLflow alone was short on volume (40 over 3 years), so a
5-repo **calibration corpus** was built instead. **MLflow's 40 sealed as held-out transfer test.**

### 5.6 The calibration set had a 39.3-point author confound (found, fixed)
v1 insider rate: **actionable 51.3%** vs **needs_info 12.0%** — gap **+39.3 pts**.
Worst: kubernetes 71.7% vs 13.3%. A judge could score well by detecting insider writing style
(`[Serve]` prefixes, internal jargon, "Proposed Fix" sections) instead of information
sufficiency — shortcut learning that collapses in deployment, where ~88% of issues are
outsider-authored.
**Fix:** v2 restricts **both** classes to `author_association == NONE`. Insider status constant →
no shortcut → also better matches deployment. v1 preserved as `*_v1_confounded.jsonl` (evidence).

---

## 6. Known limitations (must appear in README)

1. **Body edits.** GitHub returns the *current* body. An author may have edited theirs to add
   missing details after being asked → a positive that now looks complete. Not cheaply
   detectable via REST. Mitigation: spot-check for `EDIT:`/`UPDATE:` markers.
2. **Class balance.** Calibration set is ~50/50 by construction; real needs-info prevalence is
   **~3%**. Measured agreement is **not** deployment precision — false positives will dominate.
3. **Transfer assumption.** Calibrated on 5 external repos, applied to 5 watched repos. MLflow
   transfer test is the check, but it's one repo and 40 examples.
4. **Truncated pulls.** langfuse/mlflow/llama_index first pulls hit the 3,000-item ceiling
   (`MAX_PAGES=30 × 100`), so their "365-day" windows are shorter. Constants later raised to
   `LOOKBACK_DAYS=1095`, `MAX_PAGES=100`; only mlflow was re-pulled (1,551 issues).
5. **My own OSS inexperience** limits the value of hand-verification right now. Real error
   analysis is deferred to Phase 2, where only judge↔key disagreements get reviewed.

---

## 7. Design decisions locked

- **Dedupe: CUT** (0.7% duplicate rate)
- **Classifier: DEMOTED** to fallback for the 29% unlabelled
- **Reproduction-readiness: PROMOTED** to Layer A headline metric
- **PII redaction: CUT** (issues rarely contain PII)
- **Queue/scheduler: KEPT** — polling 5 repos on a schedule is real throughput
- **pgvector: KEPT** — [ARCH] for fit-matching (its dedupe use is gone)
- **`author_association` may become an explicit runtime feature** in Layer B ranking — it's
  available on every issue, so use it directly rather than letting an LLM infer it from prose.

---

## 8. Remaining in Phase 0

- [ ] Run `build_calibration_set_v2.py`; verify confound gone; commit both versions
- [ ] **Golden set** ~120 issues, stratified, frozen — 40 held out untouched until Phase 2
- [ ] **Relevance set** ~60 — "would I take this?" + self-consistency re-label after a week
- [ ] **`profile/profile.yaml`** — languages, frameworks, anti-preferences, free-text
      "what I want to work on", own-repo embeddings
- [ ] **`taxonomy/v1.0`** — promote from v0.1 seed using the full corpus
- [ ] **LinkedIn post 1** — the ground-truth finding (§5.2) or the confound (§5.6)

**Phase 0 DoD:** all fixtures frozen + committed · MLflow sealed · every cut component has a
one-line measured justification in the README.

---

## 9. Phase map

| Phase | What | Status |
|---|---|---|
| **0** | Data & ground-truth foundation | **← here, ~75%** |
| 1 | MCP domain server (standalone repo, PyPI + Registry) | |
| 2 | Single-agent baseline — **the arbiter** | |
| 3 | LangGraph objective core (Layer A) — [MEASURED] vs Phase 2 | |
| 4 | Fit ranking + daily digest (Layer B) | |
| 5 | HITL gate + claim drafting; write-scoped token introduced here | |
| 6 | Self-correction loop — [MEASURED], cut if no lift | |
| 7 | Evals deep + CI gate; MLflow transfer test run **once** | |
| 8 | Cost (model router) + safety (prompt-injection scanning) | |
| 9 | Package + dogfood — README, demo, video, first real PRs | |

---

## 10. Metrics I'll be able to claim

**Anchor:** *multi-agent lifted end-to-end success X% → Y% over a single-agent baseline*
(relative — unaffected by label noise)

**Layer A:** readiness agreement vs maintainer judgement across 5 ecosystems · MLflow transfer
result · tool-call accuracy · loop rate · recovery rate · injection catch rate · CI regressions caught
**Layer A (caveated):** classifier F1 vs author-declared labels, fallback path only
**Layer B:** precision@k · MRR · self-consistency %
**Payoff:** PRs opened → PRs merged
**Null results (assets):** dedupe cut · label-source finding · author confound found+fixed · reflexion lift (pending)

---

## 11. Timing

- **Portfolio:** can add now (in-progress + build log is an asset)
- **Resume:** after Phase 2 (published MCP server = linkable artifact + first real numbers)
- **LinkedIn:** post 1 now — lead with a finding, not an announcement
- **Applications: never paused.**
