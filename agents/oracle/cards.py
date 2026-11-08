import json

from fetch_hackkit import cards

from core.schemas import HuntResult, PortVersion, Request


def _short(x, n=300):
    s = json.dumps(x, ensure_ascii=False, sort_keys=True) if not isinstance(x, str) else x
    return s if len(s) <= n else s[:n] + "…"


def hunt_form():
    return cards.form("Hunt the ghost", [
        cards.field("description", "Describe a weird input", "textarea", placeholder="Plain English"),
        cards.field("raw", "Or raw JSON: {method, path, headers, body}", "textarea"),
    ], submit=cards.cta("Prepare hunt", "prepare_hunt", primary=True))


def stake_review(req: Request, offer_fet: str = "5"):
    return cards.review("Confirm your hunt", rows={
        "Method": req.method, "Path": req.path, "Headers": _short(req.headers), "Body": _short(req.body),
        "Stake": f"1 testnet FET (returned + {offer_fet} FET if the port diverges, forfeited if it holds)",
        "Bounty offer": f"{offer_fet} FET now: it grows each hour nobody breaks the port",
    }, approve=cards.cta("Stake 1 FET and hunt", "hunt", primary=True, request=req.model_dump()),
       reject=cards.cta("Cancel", "cancel_hunt"))


def hunt_card(r: HuntResult):
    if not r.diverged:
        verdict = "HELD"
    elif r.tx_bounty:
        verdict = "DIVERGED, bounty paid"
    else:
        verdict = "DIVERGED, bounty FAILED"
    if r.original.body == "FAILED":
        verdict = "FAILED: the original did not answer"
    return cards.detail(f"Hunt: {verdict}", rows={
        "Input": _short(r.input.model_dump()),
        "Original": f"{r.original.status} {_short(r.original.body)}",
        "Ghost": f"{r.port.status} {_short(r.port.body)}",
        "Stake tx": r.tx_stake,
        "Bounty tx": r.tx_bounty or "none",
    }, ctas=[cards.cta("Hunt again", "hunt_form")])


def challenge_form():
    return cards.form("Challenge the port: free, no stake", [
        cards.field("description", "Describe an input that might trip it up", "textarea", placeholder="Plain English"),
        cards.field("raw", "Or raw JSON: {method, path, headers, body}", "textarea"),
    ], submit=cards.cta("Run it on both", "challenge_run", primary=True))


def challenge_card(r: dict):
    """Free try. It may report a difference, never a payment."""
    o, p = r["original"], r["port"]
    if not r["diverged"]:
        title, note = "Challenge: the port held", "Both programs gave the same answer. That is evidence, not proof."
    elif r["new"]:
        title, note = f"Challenge: you found a difference ({r['divergence_id']})", (
            "Credited to you, unpaid: this was a free try. It goes into the improvement loop. "
            "Stake on a new input with Hunt to earn a bounty.")
    else:
        title, note = f"Challenge: already known ({r['divergence_id']})", "Someone found this one first, so it cannot be claimed again."
    return cards.detail(title, rows={
        "Port version": r["version"], "Input": _short(r["input"]),
        "Original": f"{o['status']} {_short(o['body'])}", "Port": f"{p['status']} {_short(p['body'])}",
        "Payment": "none (free challenge)",
    }, ctas=[cards.cta("Try another", "challenge_form"), cards.cta("Hunt for a bounty", "hunt_form")], narration=note)


def gate_rows(v: PortVersion) -> dict:
    return {"Held-out equivalence": f"{v.heldout_equivalence:.1%}", "Regressions": ", ".join(v.regressions) or "none",
            "Commit": v.commit[:10], "Gate": v.reason or ""}
