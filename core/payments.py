"""Stake verification and bounty payout. Everything returns None unless the chain
confirmed it; callers map None to FAILED. No card may claim an unverified payment."""
from decimal import Decimal

STAKE_FET = "1"
BOUNTY_FET = "5"
_DENOM = "atestfet"


def _client():
    from cosmpy.aerial.client import LedgerClient, NetworkConfig
    return LedgerClient(NetworkConfig.fetchai_stable_testnet())


def _record(db, **doc) -> bool:
    """False if this tx hash was already recorded, which blocks stake replay."""
    from pymongo.errors import DuplicateKeyError
    try:
        db.payments.insert_one(doc)
        return True
    except DuplicateKeyError:
        return False


def payer_of(tx_hash: str, client=None) -> str | None:
    """The on-chain sender, so bounties go to the wallet that staked rather than a claimed one."""
    try:
        tx = (client or _client()).query_tx(tx_hash)
        if not tx.is_successful():
            return None
        return (tx.events.get("transfer") or {}).get("sender")
    except Exception:
        return None


def stake(db, tx_hash: str, recipient_wallet: str, hunter: str, verify=None) -> str | None:
    """Verified and first use of this tx: returns the hash. Otherwise None."""
    if verify is None:
        from fetch_hackkit.payments import verify_fet_transfer as verify
    ok, _reason = verify(transaction_id=tx_hash, amount=STAKE_FET, recipient_wallet=recipient_wallet)
    if not ok or not _record(db, tx_hash=tx_hash, kind="stake", hunter=hunter, amount_fet=STAKE_FET):
        return None
    return tx_hash


def bounty(db, wallet, to_address: str, hunter: str, divergence_id: str, client=None) -> str | None:
    """Stake + bounty back to the hunter. Returns a hash only after on-chain success."""
    atto = int((Decimal(STAKE_FET) + Decimal(BOUNTY_FET)) * 10**18)
    try:
        c = client or _client()
        tx = c.send_tokens(to_address, atto, _DENOM, wallet)
        tx.wait_to_complete()
        if not tx.response.is_successful():
            return None
        h = tx.tx_hash
    except Exception:
        return None
    _record(db, tx_hash=h, kind="bounty", hunter=hunter, divergence_id=divergence_id, amount_fet="6")
    return h
