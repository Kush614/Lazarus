from fetch_hackkit import cards

from core.schemas import Hypothesis, PortVersion

BADGE = {"OBSERVED": "success", "INFERRED": "warning", "REFUTED": "danger"}


def dig_card(s: dict, strategy_version: int):
    return cards.detail("The dig", rows={
        "Endpoints": ", ".join(s["endpoints"]),
        "OBSERVED / INFERRED / REFUTED": f"{s['OBSERVED']} / {s['INFERRED']} / {s['REFUTED']}",
        "Claims resolved by probing": f"{s['resolved_pct']}%", "Probes run": s["probes"],
        "Strategy version": strategy_version,
    }, ctas=[cards.cta("Show the dig", "show_dig"), cards.cta("Resurrect", "resurrect", primary=True)])


def ledger_card(hs: list[Hypothesis]):
    items = []
    for h in hs[:20]:
        conf = f"confidence {h.confidence:.2f}" if h.status == "INFERRED" else "evidence " + ", ".join(h.evidence)
        items.append(cards.item(h.id, h.claim, action="probe_this", cta_label="Probe this", subtitle=f"{h.id} · {h.endpoint}",
                                badges=[cards.badge(h.status, BADGE[h.status])], secondary_text=f"{conf} · from {h.source}"))
    return cards.carousel("Hypothesis ledger", items, subtitle=f"Showing {len(items)} of {len(hs)}")


def resurrection_card(v: PortVersion):
    """Held-out contents never appear here: the gate only ever returns a score and opaque ids."""
    return cards.detail(f"Resurrected: port v{v.version}", rows={
        "Held-out equivalence": f"{v.heldout_equivalence:.1%}", "Commit": v.commit[:10], "Regressions": ", ".join(v.regressions) or "none",
        "Gate": v.reason or "",
    }, ctas=[cards.cta("Adopt", "decide", primary=True, version=v.version, approved=True),
             cards.cta("Roll back", "decide", version=v.version, approved=False)])


def version_review(v: PortVersion, parent: float | None, strategy_summary: str):
    return cards.review(f"Port v{v.version} vs v{v.parent}", rows={
        "Equivalence": f"{(parent or 0):.1%} → {v.heldout_equivalence:.1%}",
        "Regressions": ", ".join(v.regressions) or "none", "Strategy change": strategy_summary, "Gate": v.reason or "",
    }, approve=cards.cta("Adopt", "decide", primary=True, version=v.version, approved=True),
       reject=cards.cta("Roll back", "decide", version=v.version, approved=False))


def decided_card(v: PortVersion):
    return cards.info(f"Port v{v.version}: {v.status}", rows={
        "Held-out equivalence": f"{v.heldout_equivalence:.1%}", "Regressions": ", ".join(v.regressions) or "none", "Gate": v.reason or ""})


def reveal_card(r: dict):
    return cards.info("Reveal", rows={
        "Seal tx": r["seal_tx"], "Sealed at": r["sealed_at"], "Source hash match": "yes" if r["source_match"] else "NO",
        "Held-out hash match": "yes" if r["heldout_match"] else "NO",
        "Inference hit-rate": f"{r['correct']}/{r['scored']} INFERRED claims correct", "Wrong guesses": "; ".join(r["wrong"][:3]) or "none"})
