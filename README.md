# OSS Contribution Copilot

A supervised multi-agent system that watches selected open-source repositories, triages
every new issue against maintainer-labelled ground truth, then ranks the actionable ones
against my own profile and drafts a gated "I'd like to take this" comment.

**Status:** Phase 0 — data collection and ground-truth construction.

---

## Why this exists

New contributors drown before they start: thousands of open issues, no signal about which
are actually a fit. This system answers that, and I use it myself.

It is built in two layers:

- **Layer A — objective triage core.** Classify and enrich each new issue. Ground truth is
  maintainer-assigned labels, so this layer has hard, external, reproducible metrics.
- **Layer B — personal fit ranking.** Rank triaged issues against my profile and surface a
  daily digest. Metrics here are self-labelled and reported with that caveat stated.

Nothing is ever written to GitHub without explicit human approval.

## Metrics

_Populated as each phase is measured. No number appears here until it has been measured
against a frozen fixture set._

## Design decisions

_Each component records why it exists and what measurement justifies it. Components that
were measured and found not to earn their complexity are listed here as removed._

## Quickstart

```bash
cp .env.example .env      # then fill in GITHUB_TOKEN
uv venv && source .venv/bin/activate
uv sync
docker compose up -d
```

## Licence

MIT
