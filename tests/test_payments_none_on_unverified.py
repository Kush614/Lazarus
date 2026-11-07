import mongomock

from core import ledger, payments


def db():
    d = mongomock.MongoClient().x
    ledger.ensure_indexes(d)
    return d


def test_unverified_stake_is_none():
    d = db()
    assert payments.stake(d, "T", "w", "h", verify=lambda **k: (False, "not found")) is None
    assert d.payments.count_documents({}) == 0


def test_stake_cannot_be_replayed():
    d = db()
    ok = lambda **k: (True, "verified")
    assert payments.stake(d, "T", "w", "h", verify=ok) == "T"
    assert payments.stake(d, "T", "w", "other", verify=ok) is None


class Failing:
    def send_tokens(self, *a):
        class Tx:
            tx_hash = "H"
            def wait_to_complete(self): pass
            class response:
                @staticmethod
                def is_successful(): return False
        return Tx()


class Exploding:
    def send_tokens(self, *a):
        raise RuntimeError("rpc down")


def test_failed_or_erroring_bounty_is_none():
    d = db()
    assert payments.bounty(d, None, "fetch1", "h", "D-1", client=Failing()) is None
    assert payments.bounty(d, None, "fetch1", "h", "D-1", client=Exploding()) is None
    assert d.payments.count_documents({}) == 0
