"""Studio: cards are computed from the spec by code, and nothing says PAID without a confirmed tx."""
from agents.factory import studio

SPEC = {"name": "Lucia's Oven", "industry": "Pizzeria", "pitch": "Pizza in Brooklyn.",
        "catalog": [{"name": "Pepperoni Pizza", "price": 23.0, "unit": "each"}, {"name": "Garlic Knots", "price": 6.0, "unit": "each"}],
        "policies": [{"key": "Hours", "value": "11am-11pm"}], "examples": [], "trap": "catering"}
PLUMBER = {"business_id": "biz-p", "handle": "pipes-1", "spec": {**SPEC, "name": "Pipes", "catalog": [{"name": "Drain Cleaning", "price": 149.0, "unit": "each"}]}}


def test_quote_total_is_code_not_model():
    card, _ = studio.card_for(SPEC, "quote for 3 pepperoni pizza")
    assert card["kind"] == "quote" and card["rows"]["Total"] == "$69.00" and card["rows"]["Quantity"] == "3"


def test_unknown_item_is_referred_to_a_studio_business_that_sells_it():
    card, ref = studio.card_for(SPEC, "book drain cleaning tomorrow", others=[PLUMBER])
    assert ref is PLUMBER and card["title"] == "Referred to Pipes" and card["rows"]["Price"] == "$149.00 each"


def test_price_check_rejects_a_wrong_number():
    assert studio._price_ok(23.0, "It is $23.00 each.")
    assert not studio._price_ok(23.0, "It is $25 each.")
    assert not studio._price_ok(6.0, "Garlic Knots are $6.0 million each.")


def test_order_is_not_paid_when_the_chain_did_not_confirm(monkeypatch):
    class DB:
        class _C:
            def insert_one(self, d): pass
            def find(self, *a, **k): return []
        studio_orders = studio_activity = studio_chats = studio = _C()
    monkeypatch.setattr(studio, "fet_usd", lambda: None)  # no live price: no payment is attempted
    o = studio.pay(DB(), {"business_id": "biz-x", "handle": "h", "spec": SPEC}, SPEC["catalog"][0])
    assert o["status"] == "failed" and "tx_hash" not in o
