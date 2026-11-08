"""Proof receipt: one small, checkable summary of a run.

Anyone holding a receipt can check three things without trusting LAZARUS:
  1. its id is the sha256 of its own contents (nothing was edited after issue),
  2. the seal it cites is a real dorado-1 transaction whose memo carries the source and
     held-out hashes (the tests were fixed before the work),
  3. every adopted version passed the gate rule: a higher score and zero regressions.
It holds scores and counts only. No held-out request, expected answer or relic source.
"""
import hashlib
import json
import pathlib
import time

import httpx

ROOT = pathlib.Path(__file__).parent.parent
REST = "https://rest-dorado.fetch.ai/cosmos/tx/v1beta1/txs/"
EXPLORER = "https://explore-dorado.fetch.ai/transactions/"


def _canon(doc: dict) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def receipt_id(body: dict) -> str:
    return hashlib.sha256(_canon({k: v for k, v in body.items() if k != "id"})).hexdigest()


def build(db, root: pathlib.Path = ROOT, report_sha256: str | None = None, now=None) -> dict:
    seal = json.loads((root / "SEAL.json").read_text())
    versions = [{"version": d["version"], "equivalence": round(d["heldout_equivalence"], 4), "status": d["status"],
                 "regressions": len(d.get("regressions", [])), "parent": d.get("parent"), "commit": d.get("commit", "")}
                for d in db.port_versions.find({}, {"_id": 0}).sort("version", 1)]
    count = lambda s: db.hypotheses.count_documents({"status": s})
    paid = db.payments.count_documents({"kind": "bounty"})
    body = {
        "kind": "lazarus-proof-receipt", "format": 1,
        "issued_at": now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seal": {"tx": seal["tx_hash"], "network": seal["network"], "source_hash": seal["source_hash"],
                 "heldout_hash": seal["heldout_hash"], "sealed_at": seal["timestamp"], "explorer": EXPLORER + seal["tx_hash"]},
        "claims": {"observed": count("OBSERVED"), "inferred": count("INFERRED"), "refuted": count("REFUTED")},
        "probes": db.traces.count_documents({"origin": "probe"}),
        "versions": versions,
        "divergences": db.divergences.count_documents({}),
        "verified_bounties": paid,
        "report_sha256": report_sha256,
    }
    body["id"] = receipt_id(body)
    return body


def _chain_memo(tx: str, get=None) -> tuple[str | None, str | None]:
    """(memo, timestamp) from the chain, or (None, reason)."""
    try:
        r = (get or (lambda u: httpx.get(u, timeout=20)))(REST + tx)
        d = r.json()
        if d.get("tx_response", {}).get("code", 1) != 0:
            return None, "the seal transaction failed on chain"
        return d["tx"]["body"]["memo"], d["tx_response"]["timestamp"]
    except Exception as e:
        return None, f"could not reach the chain: {type(e).__name__}"


def verify(receipt: dict, get=None) -> dict:
    """Returns {"ok": bool, "checks": [{name, ok, detail}]}. `get` is injectable for tests."""
    checks = []

    def check(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    check("untampered", receipt.get("id") == receipt_id(receipt),
          "the id matches the sha256 of the contents" if receipt.get("id") == receipt_id(receipt) else "contents changed after issue")
    seal = receipt.get("seal", {})
    memo, extra = _chain_memo(seal.get("tx", ""), get)
    if memo is None:
        check("sealed on chain", False, extra)
    else:
        good = f"src:{seal.get('source_hash')}" in memo and f"ho:{seal.get('heldout_hash')}" in memo
        check("sealed on chain", good, f"dorado-1 memo carries both hashes, block time {extra}" if good else "the memo does not match these hashes")
    best, bad = None, []
    for v in receipt.get("versions", []):
        if v["status"] != "ADOPTED":
            continue
        if v["regressions"] or (best is not None and v["equivalence"] <= best):
            bad.append(v["version"])
        best = v["equivalence"]
    check("gate rule held", not bad, "every adopted version scored higher with zero regressions" if not bad else f"versions {bad} broke the rule")
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
