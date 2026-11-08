"""Trust price: the bounty offer grows the longer the adopted port goes unbroken.

A large unclaimed bounty is a public, money-backed signal that nobody has been able to
break the port. Any divergence on the adopted version resets the clock. The oracle pays
the offer that stood when the divergence was found, so the number on screen is the
number paid. Times come from Mongo ObjectIds, which the server stamps on insert.
"""
import datetime as dt

from core import ledger

BASE_FET = 5.0
STEP_FET = 0.5          # added per full hour unbroken
CAP_FET = 20.0


def _ts(doc) -> dt.datetime:
    return doc["_id"].generation_time


def state(db, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    adopted = ledger.latest_adopted(db)
    if not adopted:
        return {"version": None, "bounty_fet": BASE_FET, "base_fet": BASE_FET, "unbroken_minutes": 0,
                "challenges_survived": 0, "last_divergence_at": None, "history": []}
    v = adopted["version"]
    since = _ts(adopted)
    last_div = db.divergences.find_one({"port_version": v}, sort=[("_id", -1)])
    if last_div and _ts(last_div) > since:
        since = _ts(last_div)
    minutes = max(0, int((now - since).total_seconds() // 60))
    offer = min(CAP_FET, BASE_FET + STEP_FET * (minutes // 60))
    survived = db.challenges.count_documents({"version": v, "diverged": False})
    hist, t = [], since
    while t <= now and len(hist) < 48:
        hours = int((t - since).total_seconds() // 3600)
        hist.append({"at": t.isoformat(), "bounty_fet": min(CAP_FET, BASE_FET + STEP_FET * hours)})
        t += dt.timedelta(minutes=30)
    hist.append({"at": now.isoformat(), "bounty_fet": offer})
    return {"version": v, "bounty_fet": offer, "base_fet": BASE_FET, "unbroken_minutes": minutes,
            "challenges_survived": survived, "last_divergence_at": _ts(last_div).isoformat() if last_div else None,
            "history": hist}


def offer(db) -> str:
    """The bounty in FET as a string, for payments.bounty."""
    return f"{state(db)['bounty_fet']:g}"
