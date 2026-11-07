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


def stake_review(req: Request):
    return cards.review("Confirm your hunt", rows={
        "Method": req.method, "Path": req.path, "Headers": _short(req.headers), "Body": _short(req.body),
        "Stake": "1 testnet FET (returned + 5 FET if the ghost diverges, forfeited if it holds)",
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


def gate_rows(v: PortVersion) -> dict:
    return {"Held-out equivalence": f"{v.heldout_equivalence:.1%}", "Regressions": ", ".join(v.regressions) or "none",
            "Commit": v.commit[:10], "Gate": v.reason or ""}
