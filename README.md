# LAZARUS

**Raise dead software. Pay anyone who proves the ghost isn't the original.**

Give LAZARUS a compiled program with no source. It probes it, keeps a ledger of claims tagged OBSERVED (with the trace that proves it) or INFERRED (with a confidence), rewrites the program in Python, and puts a FET bounty on any input where the rewrite and the original disagree. Each divergence becomes a versioned improvement to its digging strategy, adopted only if it raises the score on a sealed held-out set with zero regressions.

Tracks: Software Archaeology (primary), Trust but Verify, The System That Gets Better.

## Agents

| Agent | Brain | Role |
|---|---|---|
| `@lazarus-digger` | Muse Spark | ASI:One entry point. Forms claims, diagnoses divergences, owns `strategy.md`. |
| `@lazarus-prober` | Muse Code | Writes probes, the port, and regression tests. |
| `@lazarus-oracle` | none, deterministic | Runs both programs, scores the gate, holds the money. Cannot read the claims or the port source. |

## The seal

`SEAL.json` records one Fetch testnet transaction whose memo holds `sha256(source)` and `sha256(held-out set)`, sent before the first dig. `Reveal` decrypts the source and checks it against the chain.

## Run it

```bash
uv sync
cp .env.example .env              # fill in the keys
docker compose up -d mongo
uv run pytest
uv run python -m agents.oracle.agent
uv run python -m agents.prober.agent
uv run python -m agents.digger.agent
```

Then in ASI:One: `@lazarus-digger Exhume <image>`, `Show the dig`, `Resurrect`, `@lazarus-oracle Hunt <input>`, `Reveal`.

## What was built when

Judges should read this section.

- **Before the hackathon's 10:45 AM start, on Fri Nov 6:** the relic and sealed set, `core/`, the agent code, and the tests. Commit timestamps show exactly what.
- **The relic's author knew its behavior,** and also wrote the digger's prompts and strategy v1. Strategy v1 is deliberately generic and names none of the relic's specifics, but that is a design choice by someone who knew the answers, not a blind experiment.
- **`port/app.py` v0 is a hand-written stub,** labeled as such. Every later version is generated.
- **Any deliberately bad version used to demonstrate rollback is labeled as seeded.**

No code was ported from earlier projects.
