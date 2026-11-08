#!/usr/bin/env python3
"""Checks a LAZARUS proof receipt against its own hash and the public chain.
usage: uv run python scripts/verify_receipt.py evidence/receipt.json
       uv run python scripts/verify_receipt.py --issue   (writes evidence/receipt.json from Mongo)"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from core import receipt

if len(sys.argv) > 1 and sys.argv[1] == "--issue":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from core import ledger
    report = ROOT / "evidence" / "report.md"
    import hashlib
    sha = hashlib.sha256(report.read_bytes()).hexdigest() if report.exists() else None
    r = receipt.build(ledger.connect(), ROOT, report_sha256=sha)
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence" / "receipt.json").write_text(json.dumps(r, indent=2))
    print(f"wrote evidence/receipt.json  id={r['id']}")
    path = ROOT / "evidence" / "receipt.json"
else:
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "evidence" / "receipt.json")
result = receipt.verify(json.loads(path.read_text()))
for c in result["checks"]:
    print(("PASS " if c["ok"] else "FAIL ") + f"{c['name']}: {c['detail']}")
print("RECEIPT OK" if result["ok"] else "RECEIPT FAILED")
sys.exit(0 if result["ok"] else 1)
