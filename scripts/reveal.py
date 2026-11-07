#!/usr/bin/env python3
"""The only code allowed to decrypt the relic's source. Checks the seal against the chain,
then scores the ledger's INFERRED claims against the real code. --json for the digger."""
import hashlib
import io
import json
import os
import pathlib
import sys
import tarfile
from typing import Literal

import httpx
import pyrage
from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from core import gate, ledger
from core.meta import spark

REST = "https://rest-dorado.fetch.ai/cosmos/tx/v1beta1/txs/"


class Score(BaseModel):
    hypothesis_id: str
    verdict: Literal["correct", "wrong", "partial"]


class Scores(BaseModel):
    scores: list[Score]


def chain_memo(tx_hash: str) -> str:
    r = httpx.get(REST + tx_hash, timeout=30)
    r.raise_for_status()
    return r.json()["tx"]["body"]["memo"]


def main():
    seal = json.loads((ROOT / "SEAL.json").read_text())
    tar = pyrage.decrypt((ROOT / "relic/source.tar.age").read_bytes(), [pyrage.x25519.Identity.from_str(os.environ["AGE_KEY_SOURCE"])])
    memo = chain_memo(seal["tx_hash"])
    source_match = hashlib.sha256(tar).hexdigest() == seal["source_hash"] and f"src:{seal['source_hash']}" in memo
    heldout_match = gate.heldout_hash() == seal["heldout_hash"] and f"ho:{seal['heldout_hash']}" in memo
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        code = t.extractfile("main.go").read().decode()
    db = ledger.connect()
    inferred = [{"id": d["id"], "endpoint": d["endpoint"], "claim": d["claim"]} for d in db.hypotheses.find({"status": "INFERRED"})]
    scored = spark("reveal_scoring", "Score each claim against the real source: correct, wrong, or partial. Judge only what the code does.",
                   json.dumps({"source": code, "claims": inferred}), Scores).scores if inferred else []
    by_id = {c["id"]: c["claim"] for c in inferred}
    result = {"seal_tx": seal["tx_hash"], "sealed_at": seal["timestamp"], "source_match": source_match, "heldout_match": heldout_match,
              "scored": len(scored), "correct": sum(s.verdict == "correct" for s in scored),
              "wrong": [by_id.get(s.hypothesis_id, s.hypothesis_id) for s in scored if s.verdict == "wrong"]}
    print(json.dumps(result, indent=None if "--json" in sys.argv else 2))


if __name__ == "__main__":
    main()
