"""The held-out gate. The ONLY module allowed to open heldout/ (tests/test_sealed.py).

The set is decrypted in memory and never written out. Results expose a score and opaque
ids only: no request or expected response may leave this module, or the digger could
learn from the test set and a rising score would prove nothing.
"""
import hashlib
import json
import os
import pathlib

import pyrage
from pydantic import BaseModel

from core.canon import canon_equal
from core.schemas import PortVersion, Request, Response

SET_PATH = pathlib.Path(__file__).parent.parent / "heldout" / "set.jsonl.age"


class GateReport(BaseModel):
    version: PortVersion
    matched_ids: list[str]
    failed: int  # timeouts and connection errors; each counts as a mismatch


def _plaintext(path=None, key=None) -> bytes:
    key = key or os.environ["AGE_KEY_HELDOUT"]
    data = pathlib.Path(path or SET_PATH).read_bytes()
    return pyrage.decrypt(data, [pyrage.x25519.Identity.from_str(key)])


def heldout_hash(path=None, key=None) -> str:
    return hashlib.sha256(_plaintext(path, key)).hexdigest()


def decide(equivalence: float, parent_equivalence: float | None, regressions: list[str]) -> tuple[bool, str]:
    """Adopt iff the score strictly increases AND nothing that matched before broke."""
    if regressions:
        return False, f"{len(regressions)} regressions"
    if parent_equivalence is not None and equivalence <= parent_equivalence:
        return False, f"equivalence {equivalence:.3f} did not beat parent {parent_equivalence:.3f}"
    return True, "strict improvement, zero regressions"


def evaluate(target, version: int, commit: str = "", parent: PortVersion | None = None,
             immune_ids=(), path=None, key=None) -> GateReport:
    """Scores a running target. `immune_ids` are the held-out ids matched by adopted versions.

    Status stays PROPOSED with the verdict in `reason`; adoption also needs the user or
    auto decision, which the caller records via `settle`.
    """
    entries = [json.loads(l) for l in _plaintext(path, key).decode().splitlines() if l.strip()]
    matched, failed = [], 0
    for e in entries:
        got = target.send(Request(**e["request"]))
        if got is None:
            failed += 1
        elif canon_equal(Response(**e["expected_response"]), got):
            matched.append(e["id"])
    equivalence = len(matched) / len(entries)
    regressions = sorted(set(immune_ids) - set(matched))
    ok, reason = decide(equivalence, parent.heldout_equivalence if parent else None, regressions)
    return GateReport(
        version=PortVersion(version=version, commit=commit, heldout_equivalence=equivalence,
                            regressions=regressions, status="PROPOSED",
                            parent=parent.version if parent else None,
                            reason=("eligible: " if ok else "blocked: ") + reason),
        matched_ids=matched, failed=failed)


def settle(report: GateReport, approved: bool, decided_by: str) -> PortVersion:
    """Final status. The gate's block cannot be overridden by approval."""
    v = report.version.model_copy()
    eligible = (v.reason or "").startswith("eligible")
    v.status = "ADOPTED" if eligible and approved else "ROLLED_BACK"
    v.decided_by = decided_by
    return v
