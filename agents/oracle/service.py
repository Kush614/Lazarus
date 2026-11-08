"""Oracle logic with no LLM and no transport. It runs the port only as a black box and
never reads the digger's claims or the port source (tests/test_oracle_blind.py)."""
import hashlib
import json

from pymongo.errors import DuplicateKeyError

from core import gate as gate_mod
from core import ledger, payments
from core.canon import canon_equal
from core.diff import unified
from core.gate import GateReport
from core.schemas import Divergence, HuntResult, PortVersion, Request, Response, Trace

FAILED = Response(status=0, headers={}, body="FAILED")


def input_hash(req: Request) -> str:
    return hashlib.sha256(json.dumps(req.model_dump(), sort_keys=True).encode()).hexdigest()


class Oracle:
    def __init__(self, db, repo, original, port_factory):
        self.db, self.repo, self.original, self.port_factory = db, repo, original, port_factory

    def run_probe(self, req: Request) -> Trace | None:
        got = self.original.send(req)
        if got is None:
            self.db.failures.insert_one({"kind": "probe_timeout", "request": req.model_dump()})
            return None
        t = Trace(id=ledger.next_id(self.db, "T"), request=req, response=got, origin="probe", target="original")
        self.db.traces.insert_one(t.model_dump())
        return t

    def gate(self, version: int) -> PortVersion:
        commit = self.repo.propose(version)
        parent = ledger.latest_adopted(self.db)
        parent_pv = PortVersion(**{k: v for k, v in parent.items() if k != "_id" and k in PortVersion.model_fields}) if parent else None
        with self.port_factory(version) as target:
            report = gate_mod.evaluate(target, version, commit, parent_pv, ledger.immune_ids(self.db))
        self.db.port_versions.insert_one({**report.version.model_dump(), "matched_ids": report.matched_ids, "failed": report.failed})
        return report.version

    def decide(self, version: int, approved: bool, decided_by: str) -> PortVersion:
        doc = self.db.port_versions.find_one({"version": version, "status": "PROPOSED"})
        if doc is None:
            raise ValueError(f"no proposed version {version}")
        parent = self.db.port_versions.find_one({"version": doc.get("parent"), "status": "ADOPTED"}) if doc.get("parent") is not None else None
        fields = {k: v for k, v in doc.items() if k in PortVersion.model_fields}
        v = gate_mod.settle(GateReport(version=PortVersion(**fields), matched_ids=doc["matched_ids"], failed=doc["failed"]), approved, decided_by)
        if v.status == "ADOPTED":
            self.repo.adopt(version, v.heldout_equivalence, parent["heldout_equivalence"] if parent else None)
            ledger.remember_matches(self.db, doc["matched_ids"], version)
        else:
            self.repo.rollback(doc["commit"], version, v.heldout_equivalence, v.regressions)
        self.db.port_versions.update_one({"_id": doc["_id"]}, {"$set": {"status": v.status, "decided_by": decided_by}})
        return v

    def compare(self, req: Request, port_target, found_by: str) -> dict:
        """The hunt's comparison with no stake and no bounty, for LAZARUS's own scout.
        A difference is recorded, so it cannot later be claimed as a paid find on this version."""
        r = self.challenge(req, port_target, found_by)
        return {"diverged": r["diverged"], "divergence_id": r["divergence_id"]}

    def challenge(self, req: Request, port_target, who: str) -> dict:
        """Free 'try to break it': runs both programs and returns the evidence. A difference is
        recorded and credited to `who`, unpaid, so the same input cannot be staked on afterwards
        (otherwise a free try followed by a stake would be a guaranteed bounty)."""
        adopted = ledger.latest_adopted(self.db)
        version = adopted["version"] if adopted else 0
        original, port = self.original.send(req), port_target.send(req)
        if original is None:
            self.db.failures.insert_one({"kind": "compare_original_timeout", "request": req.model_dump()})
            raise ValueError("the original did not answer")
        port = port or FAILED
        out = {"version": version, "input": req.model_dump(), "original": original.model_dump(), "port": port.model_dump()}
        self.db.challenges.insert_one({"version": version, "who": who, "input_hash": input_hash(req), "diverged": not canon_equal(original, port)})
        if canon_equal(original, port):
            return {**out, "diverged": False, "divergence_id": None, "new": False, "diff": ""}
        h = input_hash(req)
        known = self.db.divergences.find_one({"input_hash": h, "port_version": version})
        if known:
            return {**out, "diverged": True, "divergence_id": known["id"], "new": False, "diff": known["diff"], "found_by": known["found_by"]}
        d = Divergence(id=ledger.next_id(self.db, "D"), input=req, original=original, port=port,
                       diff=unified(original, port), found_by=who, port_version=version)
        try:
            self.db.divergences.insert_one({**d.model_dump(), "input_hash": h})
        except DuplicateKeyError:
            known = self.db.divergences.find_one({"input_hash": h, "port_version": version})
            return {**out, "diverged": True, "divergence_id": known["id"], "new": False, "diff": known["diff"], "found_by": known["found_by"]}
        return {**out, "diverged": True, "divergence_id": d.id, "new": True, "diff": d.diff, "found_by": who}

    def already_claimed(self, req: Request) -> bool:
        """Checked before asking for a stake: the same input cannot be paid twice per version."""
        adopted = ledger.latest_adopted(self.db)
        return bool(adopted and self.db.divergences.find_one({"input_hash": input_hash(req), "port_version": adopted["version"]}))

    def hunt(self, hunter: str, req: Request, tx_stake: str, recipient_wallet: str, port_target,
             pay_bounty, verify=None) -> HuntResult | None:
        """None means the stake failed verification, and nothing was executed."""
        if payments.stake(self.db, tx_stake, recipient_wallet, hunter, verify=verify) is None:
            self.db.failures.insert_one({"kind": "stake_unverified", "tx": tx_stake, "hunter": hunter})
            return None
        original, port = self.original.send(req), port_target.send(req)
        adopted = ledger.latest_adopted(self.db)
        version = adopted["version"] if adopted else 0
        if original is None:
            # The original never answered, so nothing was proven. No bounty, and the hunter is told FAILED.
            self.db.failures.insert_one({"kind": "hunt_original_timeout", "tx": tx_stake})
            result = HuntResult(hunter=hunter, input=req, diverged=False, original=FAILED, port=port or FAILED, tx_stake=tx_stake)
            self.db.hunts.insert_one(result.model_dump())
            return result
        port = port or FAILED
        diverged = not canon_equal(original, port)
        tx_bounty = div_id = None
        if diverged:
            d = Divergence(id=ledger.next_id(self.db, "D"), input=req, original=original, port=port,
                           diff=unified(original, port), found_by=hunter, port_version=version)
            div_id = d.id
            # Written before paying: the unique index stops a concurrent double payout.
            try:
                self.db.divergences.insert_one({**d.model_dump(), "input_hash": input_hash(req)})
            except DuplicateKeyError:
                div_id = None  # lost a race for the same input: real divergence, already claimed
            else:
                tx_bounty = pay_bounty(d)
                self.db.divergences.update_one({"id": d.id}, {"$set": {"tx_bounty": tx_bounty}})
        result = HuntResult(hunter=hunter, input=req, diverged=diverged, original=original, port=port,
                            tx_stake=tx_stake, tx_bounty=tx_bounty, divergence_id=div_id)
        self.db.hunts.insert_one(result.model_dump())
        return result
