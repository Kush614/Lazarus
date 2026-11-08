import json

import mongomock

from agents.oracle.service import Oracle
from core import intent, ledger, receipt
from core.schemas import Request, Response

REQ = Request(method="GET", path="/x")
A, B = Response(status=200, body={"a": 1}), Response(status=200, body={"a": 2})
SEAL_TX = "7A3C8BE99C0A78365C4F6A13EC769EFFA7FE5844535C1D1A274F794742E6A9D8"


class T:
    def __init__(self, reply):
        self.reply = reply

    def send(self, req):
        return self.reply


def oracle(original=A):
    d = mongomock.MongoClient().x
    ledger.ensure_indexes(d)
    return Oracle(d, None, T(original), None), d


# --- Challenge me -------------------------------------------------------------

def test_challenge_held_records_nothing():
    o, d = oracle()
    r = o.challenge(REQ, T(A), "judge")
    assert not r["diverged"] and r["divergence_id"] is None and d.divergences.count_documents({}) == 0


def test_challenge_difference_is_credited_unpaid_and_blocks_a_later_stake():
    o, d = oracle()
    d.port_versions.insert_one({"version": 1, "status": "ADOPTED", "heldout_equivalence": 0.5})
    assert o.already_claimed(REQ) is False
    r = o.challenge(REQ, T(B), "judge")
    assert r["diverged"] and r["new"] and r["found_by"] == "judge" and r["version"] == 1
    doc = d.divergences.find_one({"id": r["divergence_id"]})
    assert doc["tx_bounty"] is None and d.payments.count_documents({}) == 0
    # A free find must not become a guaranteed paid hunt on the same input.
    assert o.already_claimed(REQ) is True


def test_challenge_same_input_twice_is_known_not_new():
    o, _ = oracle()
    first = o.challenge(REQ, T(B), "judge")
    again = o.challenge(REQ, T(B), "someone-else")
    assert again["new"] is False and again["divergence_id"] == first["divergence_id"] and again["found_by"] == "judge"


def test_challenge_original_silent_is_an_error_not_a_find():
    o, d = oracle(original=None)
    try:
        o.challenge(REQ, T(B), "judge")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    assert d.divergences.count_documents({}) == 0


def test_scout_compare_still_returns_its_short_shape():
    o, _ = oracle()
    assert set(o.compare(REQ, T(B), "lazarus-scout")) == {"diverged", "divergence_id"}


def test_challenge_card_never_claims_payment():
    from agents.oracle.cards import challenge_card
    o, _ = oracle()
    card = json.dumps(challenge_card(o.challenge(REQ, T(B), "judge")), default=str)
    assert "free challenge" in card and "bounty paid" not in card.lower()


# --- Proof receipt ------------------------------------------------------------

def seeded_db():
    d = mongomock.MongoClient().y
    d.hypotheses.insert_many([{"id": "H-1", "status": "OBSERVED"}, {"id": "H-2", "status": "INFERRED"}, {"id": "H-3", "status": "REFUTED"}])
    d.port_versions.insert_many([
        {"version": 1, "heldout_equivalence": 0.5, "status": "ADOPTED", "regressions": [], "parent": None, "commit": "c1"},
        {"version": 2, "heldout_equivalence": 0.7, "status": "ADOPTED", "regressions": [], "parent": 1, "commit": "c2"},
        {"version": 3, "heldout_equivalence": 0.4, "status": "ROLLED_BACK", "regressions": ["HO-1"], "parent": 2, "commit": "c3"},
    ])
    return d


class Chain:
    def __init__(self, memo, code=0):
        self.memo, self.code = memo, code

    def __call__(self, url):
        assert url.endswith(SEAL_TX)
        doc = {"tx": {"body": {"memo": self.memo}}, "tx_response": {"code": self.code, "timestamp": "2026-11-07T06:22:43Z"}}
        return type("R", (), {"json": lambda self: doc})()


def real_memo():
    seal = json.loads((receipt.ROOT / "SEAL.json").read_text())
    return seal["memo"]


def test_receipt_has_no_sealed_content_and_a_stable_id():
    r = receipt.build(seeded_db(), now="2026-11-07T00:00:00Z")
    assert r["id"] == receipt.receipt_id(r)
    assert r["claims"] == {"observed": 1, "inferred": 1, "refuted": 1}
    blob = json.dumps(r)
    assert "expected_response" not in blob and '"HO-' not in blob  # counts only, never held-out ids


def test_receipt_verifies_against_the_chain():
    r = receipt.build(seeded_db())
    out = receipt.verify(r, get=Chain(real_memo()))
    assert out["ok"], out


def test_tampered_receipt_fails():
    r = receipt.build(seeded_db())
    r["versions"][1]["equivalence"] = 0.99
    out = receipt.verify(r, get=Chain(real_memo()))
    assert not out["ok"] and not out["checks"][0]["ok"]


def test_wrong_seal_memo_fails():
    out = receipt.verify(receipt.build(seeded_db()), get=Chain("LAZARUS-SEAL src:00 ho:00"))
    assert not out["ok"] and not out["checks"][1]["ok"]


def test_unreachable_chain_fails_honestly():
    def down(url):
        raise OSError("offline")
    out = receipt.verify(receipt.build(seeded_db()), get=down)
    assert not out["ok"] and "could not reach" in out["checks"][1]["detail"]


def test_gate_rule_violation_is_caught():
    d = seeded_db()
    d.port_versions.update_one({"version": 3}, {"$set": {"status": "ADOPTED"}})
    r = receipt.build(d)
    assert not receipt.verify(r, get=Chain(real_memo()))["checks"][2]["ok"]


def test_routing_knows_the_new_intents():
    assert intent.by_rules("challenge GET /healthz") == "challenge"
    assert intent.by_rules("can I try to break it?") == "challenge"
    assert intent.by_rules("show me the proof receipt") == "receipt"
    assert intent.by_rules("hunt for a bounty") == "hunt"
