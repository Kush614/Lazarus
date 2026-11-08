"""Anchors a hash on the Fetch testnet: a 1 atestfet self-transfer whose memo carries it.

Separate from scripts/seal.py, which must never run again. The memo format is
`LAZARUS-AUDIT <kind> <sha256>`, so an auditor can find and check it on the explorer.
Returns the tx hash only after the chain confirms it; None otherwise.
"""
import os

EXPLORER = "https://explore-dorado.fetch.ai/transactions/"


def _wallet():
    from cosmpy.aerial.wallet import LocalWallet
    from cosmpy.crypto.keypairs import PrivateKey
    from uagents_core.identity import derive_key_from_seed
    from uagents.config import LEDGER_PREFIX
    seed = os.environ["AGENT_SEED_PHRASE_ORACLE"]
    return LocalWallet(PrivateKey(derive_key_from_seed(seed, LEDGER_PREFIX, 0)), prefix=LEDGER_PREFIX)


def anchor(kind: str, sha256: str, client=None, wallet=None) -> dict | None:
    if len(sha256) != 64 or not all(c in "0123456789abcdef" for c in sha256):
        raise ValueError("expected a lowercase sha256 hex digest")
    try:
        from cosmpy.aerial.client import LedgerClient, NetworkConfig
        c = client or LedgerClient(NetworkConfig.fetchai_stable_testnet())
        w = wallet or _wallet()
        memo = f"LAZARUS-AUDIT {kind[:24]} {sha256}"
        tx = c.send_tokens(w.address(), 1, "atestfet", w, memo=memo).wait_to_complete()
        if not tx.response.is_successful():
            return None
        return {"tx_hash": tx.tx_hash, "memo": memo, "wallet": str(w.address()), "explorer": EXPLORER + tx.tx_hash}
    except Exception:
        return None
