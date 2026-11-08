import datetime as dt

import mongomock
import pytest
from bson import ObjectId

from core import subq, trust_price


class R:
    def __init__(self, status, p=0.9):
        self.status_code, self.text, self._p = status, "{}", p

    def json(self):
        return {"answers": {"q": {"type": "noul", "noul": self._p}}}


def test_subq_falls_back_to_the_backup_key(monkeypatch, tmp_path):
    monkeypatch.setattr(subq, "LOG_DIR", tmp_path)
    monkeypatch.setenv("SUBQ_API_KEY", "dead")
    monkeypatch.setenv("SUBQ_API_KEY_BACKUP", "live")
    seen = []

    def post(key):
        seen.append(key)
        return R(402) if key == "dead" else R(200, 0.83)
    assert subq.yes_probability("s", "q?", "y", "n", post=post) == 0.83
    assert seen == ["dead", "live"] and len(list(tmp_path.glob("*.json"))) == 2


def test_subq_fails_loudly_when_every_key_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(subq, "LOG_DIR", tmp_path)
    monkeypatch.setenv("SUBQ_API_KEY", "a")
    monkeypatch.setenv("SUBQ_API_KEY_BACKUP", "b")
    with pytest.raises(subq.SubQError):
        subq.yes_probability("s", "q?", "y", "n", post=lambda k: R(401))


def oid(t):
    return ObjectId.from_datetime(t)


T0 = dt.datetime(2026, 11, 7, 12, 0, tzinfo=dt.timezone.utc)


def test_trust_price_grows_per_unbroken_hour_and_caps():
    d = mongomock.MongoClient().t
    d.port_versions.insert_one({"_id": oid(T0), "version": 1, "status": "ADOPTED", "heldout_equivalence": 0.6})
    assert trust_price.state(d, now=T0 + dt.timedelta(minutes=59))["bounty_fet"] == 5.0
    assert trust_price.state(d, now=T0 + dt.timedelta(hours=3, minutes=1))["bounty_fet"] == 6.5
    assert trust_price.state(d, now=T0 + dt.timedelta(days=5))["bounty_fet"] == trust_price.CAP_FET


def test_a_divergence_resets_the_clock():
    d = mongomock.MongoClient().t
    d.port_versions.insert_one({"_id": oid(T0), "version": 1, "status": "ADOPTED", "heldout_equivalence": 0.6})
    d.divergences.insert_one({"_id": oid(T0 + dt.timedelta(hours=4)), "port_version": 1, "id": "D-0001"})
    s = trust_price.state(d, now=T0 + dt.timedelta(hours=4, minutes=30))
    assert s["bounty_fet"] == 5.0 and s["unbroken_minutes"] == 30 and s["last_divergence_at"]


def test_no_adopted_port_means_base_offer():
    assert trust_price.state(mongomock.MongoClient().t)["version"] is None
