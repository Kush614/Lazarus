# LAZARUS

Raises dead software from a binary with no source, and pays anyone who proves the port wrong.

This repo must never contain the relic's source, its behavior table, the held-out set, or their generators.
They live outside the repo and are sealed by hash on-chain (SEAL.json). Muse Code runs against this repo, so anything committed here is something the agents could read.

Rules that protect the demo's credibility, enforced by tests:
- Only `core/gate.py` opens `heldout/`, and it returns only a score and opaque ids (`test_sealed.py`, `test_gate.py`).
- Only `scripts/reveal.py` decrypts the source (`test_sealed.py`).
- The oracle never imports the digger, prober or port (`test_oracle_blind.py`).
- OBSERVED needs a real trace id, attached by code and not by the model (`test_dig.py`).
- `core/payments.py` returns None unless the chain confirmed it. No card may claim an unverified payment.
- Every Spark call goes through `core/meta.py`; every Muse Code call through `agents/prober/muse_client.py`. Both log to `logs/meta/`.
- Muse Code's sandbox limits writes only. Do not widen its env, or weaken `muse_client.audit`.
- `port/` is generated. Never hand-edit it. The v0 stub is labeled.
- Run `uv run pytest` before every commit. Never run `scripts/seal.py` again.
