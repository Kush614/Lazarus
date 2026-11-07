import mongomock

from agents.oracle.service import Oracle
from core import ledger
from core.schemas import PortVersion, Request, Response


class T:
    def __init__(self, reply):
        self.reply = reply
    def send(self, req):
        return self.reply


OK = lambda **k: (True, "verified")
BAD = lambda **k: (False, "nope")
REQ = Request(method="GET", path="/x")
A, B = Response(status=200, body={"a": 1}), Response(status=200, body={"a": 2})


def svc(tmp_path=None, original=A):
    d = mongomock.MongoClient().x
    ledger.ensure_indexes(d)
    return Oracle(d, None, T(original), None), d


def test_unverified_stake_executes_nothing():
    class Boom:
        def send(self, r):
            raise AssertionError("must not execute")
    o, d = svc()
    o.original = Boom()
    assert o.hunt("h", REQ, "tx", "w", Boom(), lambda x: "b", verify=BAD) is None
    assert d.failures.count_documents({"kind": "stake_unverified"}) == 1


def test_divergence_pays_and_records():
    o, d = svc()
    r = o.hunt("h", REQ, "tx", "w", T(B), lambda x: "bounty-hash", verify=OK)
    assert r.diverged and r.tx_bounty == "bounty-hash" and d.divergences.find_one({"id": r.divergence_id})["tx_bounty"] == "bounty-hash"


def test_held_pays_nothing():
    o, d = svc()
    r = o.hunt("h", REQ, "tx", "w", T(A), lambda x: 1 / 0, verify=OK)
    assert not r.diverged and r.tx_bounty is None and d.divergences.count_documents({}) == 0


def test_failed_bounty_is_not_claimed_as_paid():
    o, _ = svc()
    r = o.hunt("h", REQ, "tx", "w", T(B), lambda x: None, verify=OK)
    assert r.diverged and r.tx_bounty is None


def test_original_timeout_never_pays():
    o, _ = svc(original=None)
    r = o.hunt("h", REQ, "tx", "w", T(B), lambda x: 1 / 0, verify=OK)
    assert not r.diverged and r.tx_bounty is None and r.original.body == "FAILED"


def test_same_input_cannot_be_paid_twice_per_version():
    o, d = svc()
    d.port_versions.insert_one(PortVersion(version=1, commit="c", heldout_equivalence=.5, regressions=[], status="ADOPTED").model_dump())
    assert not o.already_claimed(REQ)
    o.hunt("h", REQ, "tx", "w", T(B), lambda x: "b", verify=OK)
    assert o.already_claimed(REQ)
