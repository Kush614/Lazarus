# LAZARUS

**Raise dead software. Pay anyone who proves the ghost isn't the original.**

Give LAZARUS a compiled program with no source. It probes it, keeps a ledger of claims tagged OBSERVED (with the trace that proves it) or INFERRED (with a confidence), rewrites the program in Python, and puts a FET bounty on any input where the rewrite and the original disagree. Each divergence becomes a versioned improvement to its digging strategy, adopted only if it raises the score on a sealed held-out set with zero regressions.

Tracks: Software Archaeology (primary), Trust but Verify, The System That Gets Better.

## Agents

Six agents, each registered on Agentverse and speaking the Agent Chat Protocol. `@lazarus-digger` is the entry point in ASI:One.

| Agent | Brain | Role | Theme |
|---|---|---|---|
| `@lazarus-digger` | Muse Spark, ASI:One for intent | Understands the request, forms claims, diagnoses divergences, owns `strategy.md`. | Reconstructs the past |
| `@lazarus-prober` | Muse Code | Writes probes, the port, and regression tests. | Reconstructs the past |
| `@lazarus-oracle` | none, deterministic | Runs both programs, scores the gate, holds the money. Cannot read the claims or the port source. | Verifies before trusting |
| `@lazarus-sentinel` | none, deterministic | Parses every generated port and blocks unsafe code before it runs. Also reviews any Python pasted to it. | Verifies before trusting |
| `@lazarus-scout` | none, deterministic | Fires edge-case inputs at each adopted port and sends differences into the improvement loop. | Gets better |
| `@lazarus-scribe` | none, deterministic | Writes the observed vs inferred evidence report with a checkable hash. Sells the full report. | Proves the work |

### Fetch.ai integrations

- **Agentverse and ASI:One:** all six register themselves through `fetch-hackkit`, with a handle, description and README.
- **Agent Chat Protocol:** agents talk to each other over ACP. Internal commands are refused unless the sender is another LAZARUS agent (`core/trust.py`).
- **Intent routing:** rules first, then the ASI:One model for what they miss (`core/intent.py`). It works on rules alone if the key is missing.
- **Interactive Cards:** carousel (ledger, use cases, scout finds), detail, form (hunt, code review), review (stake, adopt, break the seal) and a custom layout (status).
- **Payment Protocol:** a 1 FET hunt stake with a 5 FET bounty on `@lazarus-oracle`, and a 0.5 FET report on `@lazarus-scribe`. Payments are only reported once the chain confirms them.
- **Recovery:** repeatable peer calls retry, failures show a Try again card, and a blocked port is rolled back.
- **Keeps running:** Scout watches for newly adopted versions and tests them unprompted.

### Prove it yourself

- **Challenge me, free:** `@lazarus-oracle challenge <input>` runs your input on the original binary and the adopted port and shows both answers. A difference is credited to you but not paid, and that input can no longer be staked on, so a free try can't become a guaranteed bounty. Use `Hunt` to stake for a bounty.
- **Proof receipt:** `@lazarus-digger receipt` issues a small JSON summary of the run (claims, versions, gate results, confirmed bounties) whose id is the sha256 of its contents. Checking it re-reads the seal transaction from dorado-1 and confirms the memo carries both hashes, and that every adopted version beat its parent with zero regressions. It holds counts only, never held-out content. Anyone can run `uv run python scripts/verify_receipt.py evidence/receipt.json`.
- **Demo API:** `uv run python scripts/api.py` serves the real records to the UI on `127.0.0.1:8030` (`/snapshot`, `/receipt/verify`, `POST /challenge`). It has no payment route.

### Run and check

```bash
uv run python scripts/check_ready.py   # what is missing, plus each agent's address and profile URL
uv run python scripts/prerun_dig.py    # the whole story for real, in one process, with no agent registered
scripts/run_all.sh                     # starts all six agents
uv run pytest
```

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

## Submitting

1. Submit on the Cerebral Valley event page.
2. In ASI:One, open the AIE Code Summit ASI:One Submission agent, choose **Create team (I'm the lead)** and fill in the form.
3. Add the bonus fields: the six Agentverse profile URLs from `scripts/check_ready.py`, and the shared chat URL (in ASI:One: search icon, **Current chat**, **Share chat**).
4. Confirm the submission and keep the Team ID.
