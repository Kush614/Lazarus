#!/usr/bin/env python3
"""Commits both hashes to the Fetch testnet in one tx memo and writes SEAL.json. Run before the first dig.
Refuses to run twice: a second seal would make the first one meaningless."""
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

from cosmpy.aerial.client import LedgerClient, NetworkConfig
from cosmpy.aerial.wallet import LocalWallet
from cosmpy.crypto.keypairs import PrivateKey
from dotenv import load_dotenv
from uagents.config import LEDGER_PREFIX
from uagents_core.identity import derive_key_from_seed

ROOT = pathlib.Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
out = ROOT / "SEAL.json"
if out.exists():
    sys.exit(f"{out} already exists; refusing to reseal")
h = json.loads((ROOT / ".seal_hashes.json").read_text())
wallet = LocalWallet(PrivateKey(derive_key_from_seed(os.environ["AGENT_SEED_PHRASE_ORACLE"], LEDGER_PREFIX, 0)), prefix=LEDGER_PREFIX)
client = LedgerClient(NetworkConfig.fetchai_stable_testnet())
if client.query_bank_balance(wallet.address()) == 0:
    sys.exit(f"wallet {wallet.address()} has no testnet FET; use the faucet first")
memo = f"LAZARUS-SEAL src:{h['source_hash']} ho:{h['heldout_hash']}"
tx = client.send_tokens(wallet.address(), 1, "atestfet", wallet, memo=memo).wait_to_complete()
if not tx.response.is_successful():
    sys.exit(f"seal tx failed: {tx.response.raw_log}")
out.write_text(json.dumps({**h, "tx_hash": tx.tx_hash, "memo": memo, "network": "fetchai-stable-testnet (dorado-1)",
                           "wallet": str(wallet.address()), "timestamp": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n")
print(out.read_text())
