# OSS Contribution Copilot

A supervised multi-agent system that watches open-source repositories, judges whether each new
issue is **actionable**, filters to what is **claimable**, and drafts a human-approved
"I'd like to take this" comment.

I built it to find and land my own first open-source contributions. Nothing reaches GitHub
without my explicit approval.

**Status:** ground-truth datasets built and validated; agent implementation in progress. No
performance numbers are claimed yet — this README will only ever contain measured results.

---

## Why this README leads with measurements

Most of the groundwork was spent testing whether the project's own assumptions were true. Four of
them were not. Each finding below changed the design, and three components were cut as a result.

The datasets underneath a system determine what its metrics mean. These are the checks I ran
before building anything on top of them.

---

## What I measured before building

### 1. GitHub issue labels are not maintainer judgement

The project was originally designed around a premise: maintainer-assigned labels
(`bug`, `enhancement`, `question`) are free expert ground truth for an issue classifier.

Measured across 2,568 issues from 5 repositories:

| Metric | Result |
|---|---|
| First type label applied by the **issue author** | **90.7%** |
| Applied by a maintainer | 7.6% |
| Applied by a bot | 1.7% |
| Applied within 2 minutes of creation | **92.1%** |
| Labelled within 1 hour | 93.9% |
| Median time to first type label | **0.00 h** |

A median of zero is not fast triage — it is automation. GitHub issue templates attach labels at
submission time, so the label records **which template the author selected**, not what a
maintainer concluded after reading. Feature requests filed through a bug template are labelled
`bug`.

**Consequence:** the classifier was demoted from headline component to a fallback path, and its
ground truth is described as *author-declared* throughout.

### 2. 29% of issues never receive a type label

744 of 2,568. A system that simply reads existing labels is blind to nearly a third of the
stream — and unlabelled issues are disproportionately the neglected ones, which is exactly where
an unclaimed opportunity would be.

**Consequence:** the classifier survives, scoped to that 29%.

### 3. Duplicate detection cut — 0.7% duplicate rate

Semantic duplicate detection was specced as a core feature. Measured incidence of issues closed
as duplicates: **19 of 2,568 (0.7%)** — far below the ~50 examples needed to evaluate anything.

**Consequence:** cut, along with its `pgvector` dependency.

### 4. Reproduction-readiness has real ground truth

One signal survived the audit: needs-info labels (`Needs Info`, `triage/needs-information`,
`needs repro`). Sampled applications were **100% non-author** — genuine maintainer judgement,
no template contamination. When a maintainer applies one, they are stating that the issue was
not actionable as filed.

**Consequence:** reproduction-readiness became the system's primary judgement, with a
5-ecosystem calibration corpus (§ Datasets).

### 5. A 39.3-point confound in my own dataset — found and fixed

The first calibration set paired positives (maintainer-flagged as needing info) with negatives
(issues closed as completed). While hand-checking rows, the negatives all read as though written
by project insiders. Measured:

| Class | Insider-authored |
|---|---|
| actionable (negative) | **51.3%** |
| needs_info (positive) | **12.0%** |
| **gap** | **+39.3 points** |

Worst case, kubernetes: 71.7% vs 13.3%.

Insider-written issues carry loud surface tells — component prefixes, internal jargon, "Proposed
Fix" sections. An LLM judge could have scored well on this set by detecting **writing style**
rather than information sufficiency: a shortcut that would collapse in deployment, where ~88% of
issues are outsider-authored, and would filter away precisely the newcomer-filed issues the tool
exists to surface.

**Fix:** both classes restricted to `author_association == NONE`, holding the confounder constant
(300/300 each). The confounded v1 is kept in the repository as `*_v1_confounded.jsonl`.

### 6. Personalised ranking cut — no reliable answer key

A semantic fit-ranking layer was planned. Its target definition narrowed three times under
scrutiny:

1. *personal preference* — I am new to OSS and have no formed preferences to label
2. *wantedness* (unclaimed, maintainer-requested, unblocked) — **entirely machine-readable from
   GitHub metadata**; both the model and the labelled set were redundant
3. *tractability* (would this reach a merge?) — a genuine judgement, but the answer key would be
   self-labelled by someone lacking the experience to label it reliably

Applying the same standard as Finding 1 — labels from someone guessing are not ground truth — the
layer was cut and replaced with **deterministic gates**: language filter, unclaimed, wanted, not
stale, not blocked. Cheaper, inspectable, no evaluation required.

Deferral is instrumented rather than aspirational: the digest logs every claim/skip decision, so
~2 months of real use produces a *behavioural* relevance set — better ground truth than anything
I could hand-label today, at no additional cost.

---

## Design decisions

Every component is justified as **[ARCH]** (structurally required), **[MEASURED]** (kept only if
a number beats a simpler baseline), or **[LEARN]** (a deliberate learning choice, labelled as
one). Components that lose their justification are removed.

| Component | Status | Basis |
|---|---|---|
| Reproduction-readiness judge | **[ARCH]** | only signal with real maintainer judgement |
| Human-approval gate | **[ARCH]** | nothing outbound is autonomous |
| Durable checkpointed state | **[ARCH]** | the gate requires pause → resume |
| Three-layer eval suite + CI gate | **[ARCH]** | regressions must block merges |
| Prompt-injection scanning | **[ARCH]** | issue text is attacker-controllable input to a tool-calling agent |
| Type classifier | **demoted** | fallback for the unlabelled 29% |
| MCP domain server | **[LEARN + ARCH]** | must expose derived tools, not proxy the GitHub API |
| Multi-agent topology | **[MEASURED]** | kept only if it beats the single-agent baseline |
| Self-correction loop | **[MEASURED]** | kept only if it lifts task success |
| Duplicate detection | **CUT** | 0.7% duplicate rate |
| pgvector | **CUT** | both use cases eliminated |
| Personalised ranking | **CUT** | no reliable answer key |
| PII redaction | **CUT** | issues rarely contain PII |

---

## Datasets

All fixtures are frozen and committed. Held-out splits stay sealed until final evaluation.

| Dataset | Size | Ground truth | Purpose |
|---|---|---|---|
| `calibration_dev.jsonl` | 360 (180/180) | maintainer needs-info labels | readiness judge, development |
| `calibration_test.jsonl` | 240 (120/120) | maintainer needs-info labels | held out, sealed |
| `golden_dev.jsonl` | 96 (24 per type) | author-declared labels | classifier, development |
| `golden_test.jsonl` | 52 (13 per type) | author-declared labels | held out, sealed |
| MLflow needs-info set | 40 | maintainer, 100% non-author | sealed transfer test |

**Calibration corpus** — chosen for triage discipline and ecosystem diversity, deliberately
separate from the repositories the system watches:
pandas (scientific Python) · kubernetes (infrastructure, Go) · angular (frontend, TypeScript) ·
ray (MLOps) · gradio (ML tooling).
A judge that agrees with maintainers across four languages and four triage cultures has
demonstrated generalisation; one tuned to a single repository has learned that project's house
style.

**Watched repositories:** langfuse · mlflow · llama_index · ragas · deepeval — all tools I use.

---

## Known limitations

Stated because they bound what the metrics can mean.

1. **Body edits.** GitHub returns the current issue body. An author may have edited theirs to add
   missing details after being asked, which weakens some positive labels. Not cheaply detectable
   via the REST API.
2. **Class balance.** The calibration set is 50/50 by construction; real needs-info prevalence is
   ~3%. Measured agreement is **not** deployment precision — false positives will dominate in
   production.
3. **Transfer assumption.** Calibrated on five external repositories, applied to five watched
   ones. The MLflow transfer test checks this, but with a single repository and 40 examples.
4. **Classifier distribution shift.** Evaluated on labelled issues, deployed on unlabelled ones.
   Those populations differ, so reported F1 is an optimistic estimate.
5. **Thin classes.** `documentation` drew from 87 issues in a 2,568 pool. Macro-F1 and
   distribution-weighted F1 will both be reported — the natural split is 64% bug, 3.4% docs.

---

## Architecture

```
watcher ──► normalise ──► classify (fallback) ──► readiness judge
                                                        │
                                deterministic gates ◄────┘
                                        │
                                  daily digest
                                        │
                              HUMAN APPROVAL GATE
                                        │
                                  claim comment
```

Supervisor/worker orchestration on LangGraph with a Postgres checkpointer. Routing is
deterministic Python; iteration limits are enforced in code, not prompts. Tool access runs
through a self-authored MCP server with Pydantic-validated inputs and a repository allowlist.

---

## Metrics

Populated only as measured against frozen fixtures.

| Metric | Result |
|---|---|
| Multi-agent vs single-agent baseline success | _not yet measured_ |
| Readiness agreement with maintainers (5 ecosystems) | _not yet measured_ |
| MLflow transfer result | _not yet measured_ |
| Tool-call accuracy · loop rate · recovery rate | _not yet measured_ |
| Classifier macro-F1 / weighted F1 (fallback path) | _not yet measured_ |
| Prompt-injection catch rate | _not yet measured_ |
| CI regressions caught during development | _not yet measured_ |
| Issues surfaced → PRs opened → PRs merged | _not yet measured_ |

---

## Quickstart

```bash
cp .env.example .env          # add a fine-grained GitHub PAT (read-only)
uv venv && source .venv/bin/activate
uv sync
docker compose up -d
```

Reproduce the audits behind the findings above:

```bash
python scripts/fetch_issues.py --all
python scripts/measure_label_source.py     # Finding 1
python scripts/audit_ground_truth.py       # Findings 3 and 4
python scripts/check_author_confound.py    # Finding 5
```

---

## Roadmap

- Publish the MCP server as a standalone package
- Single-agent baseline — the reference every later component must beat
- Supervised multi-agent core, measured against that baseline
- Deterministic gates and the daily digest
- Human-approval gate and claim drafting
- Full evaluation suite wired into CI, with held-out sets opened once
- Cost routing and prompt-injection defence
- First merged pull requests

---

## Licence

MIT
