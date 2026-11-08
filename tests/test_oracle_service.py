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


def test_compare_records_a_difference_without_money(db_and_oracle=None):
    import mongomock
    from agents.oracle.service import Oracle
    from core.schemas import Request, Response

    class T:
        def __init__(self, body):
            self.body = body

        def send(self, req):
            return Response(status=200, headers={"content-type": "application/json"}, body=self.body)

    d = mongomock.MongoClient().x
    d.divergences.create_index([("input_hash", 1), ("port_version", 1)], unique=True, sparse=True)
    d.port_versions.insert_one({"version": 3, "status": "ADOPTED", "heldout_equivalence": .5})
    o = Oracle(d, None, T({"a": 1}), None)
    req = Request(method="GET", path="/x")
    assert o.compare(req, T({"a": 1}), "lazarus-scout") == {"diverged": False, "divergence_id": None}
    first = o.compare(req, T({"a": 2}), "lazarus-scout")
    assert first["diverged"] and d.divergences.count_documents({}) == 1 and d.payments.count_documents({}) == 0 and d.hunts.count_documents({}) == 0
    assert o.compare(req, T({"a": 2}), "lazarus-scout") == first and d.divergences.count_documents({}) == 1
    assert o.already_claimed(req), "a scout find cannot then be claimed for a bounty"
