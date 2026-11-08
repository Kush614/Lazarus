from fetch_hackkit import cards

from agents.digger.usecases import USE_CASES
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


def reveal_review():
    return cards.review("Break the seal?", rows={"What happens": "The sealed source is decrypted and every guess gets scored.", "This cannot be undone": "New digs are refused afterwards, because they would no longer be blind."},
                        approve=cards.cta("Break the seal", "reveal", primary=True), reject=cards.cta("Not yet", "status"))


def blocked_card(version: int, findings: list[dict]):
    rows = {f'{f["file"]}:{f["line"]} {f["rule"]}': f["why"] for f in findings[:10]}
    return cards.detail(f"Port v{version} blocked by Sentinel", rows=rows or {"Reason": "No detail returned."}, ctas=[cards.cta("Try again", "resurrect", primary=True), cards.cta("Status", "status")],
                        narration="This code was rolled back and never ran, so it did not reach the gate.")


def failure_card(what: str, detail: str, action: str | None):
    ctas = [cards.cta("Try again", action, primary=True)] if action else []
    return cards.detail(f"FAILED: {what}", rows={"What went wrong": detail}, ctas=ctas + [cards.cta("Status", "status")], narration="Nothing was claimed from this attempt, and it is in the failure log.")


def use_cases_card():
    items = [cards.item(u["id"], u["title"], action="use_case", cta_label="Details", subtitle=u["fit"], badges=[cards.badge("Illustrative", "info")]) for u in USE_CASES]
    return cards.carousel("Software you can call but can't read", items, subtitle="Only the demo relic has a build behind it", narration="Where LAZARUS could go next. None of these has run live.")


def use_case_card(uid: str):
    u = next((x for x in USE_CASES if x["id"] == uid), None)
    if u is None:
        return use_cases_card()
    return cards.detail(u["title"], rows={"The problem": u["problem"], "Digs out": u["digs"], "You get": u["get"], "Fit": u["fit"]},
                        ctas=[cards.cta("All use cases", "use_cases")], narration="Illustrative.")


def status_card(s: dict, adopted: dict | None, divergences: int, findings: int, failures: int):
    """A custom layout: one line per stage, with a badge saying where it stands."""
    ui = cards.ui
    score = f'{adopted["heldout_equivalence"]:.1%}' if adopted else "none adopted"
    stage = lambda name, value, variant: ui.group([ui.text(name, "emphasis"), ui.badge(str(value), variant)])
    return cards.custom(ui.section("LAZARUS status", [
        stage("Proven", s["OBSERVED"], "success"), stage("Guessed", s["INFERRED"], "warning"), stage("Refuted", s["REFUTED"], "danger"),
        ui.divider(), stage("Adopted score", score, "info"), stage("Divergences", divergences, "danger" if divergences else "success"),
        stage("Scout differences", findings, "danger" if findings else "success"), stage("Failures logged", failures, "warning" if failures else "success"),
        ui.divider(), ui.group([ui.button("Show the dig", "show_dig"), ui.button("Resurrect", "resurrect", primary=True), ui.button("Use cases", "use_cases")]),
    ], subtitle="Six agents, one ledger"), narration="Here is where things stand.")


def help_card():
    return cards.detail("LAZARUS", rows={
        "What this does": "Raises dead software. Give me a binary with no source. I dig, port it, and pay anyone who proves the port wrong.",
        "Agents": "Digger leads. Prober writes code, Oracle judges and pays, Sentinel blocks unsafe code, Scout tests the port, Scribe writes the evidence.",
    }, ctas=[cards.cta("Start the dig", "exhume", primary=True), cards.cta("Status", "status"), cards.cta("Proof receipt", "receipt"), cards.cta("Use cases", "use_cases")])


def reveal_card(r: dict):
    return cards.info("Reveal", rows={
        "Seal tx": r["seal_tx"], "Sealed at": r["sealed_at"], "Source hash match": "yes" if r["source_match"] else "NO",
        "Held-out hash match": "yes" if r["heldout_match"] else "NO",
        "Inference hit-rate": f"{r['correct']}/{r['scored']} INFERRED claims correct", "Wrong guesses": "; ".join(r["wrong"][:3]) or "none"})


def receipt_card(r: dict, check: dict):
    """The receipt and the result of checking it, side by side. Checks are re-run, not asserted."""
    adopted = [v for v in r["versions"] if v["status"] == "ADOPTED"]
    best = f"{adopted[-1]['equivalence']:.1%} (v{adopted[-1]['version']})" if adopted else "no adopted version yet"
    rows = {"Receipt id": r["id"][:16] + "…", "Seal tx": r["seal"]["tx"][:16] + "…",
            "Claims proven / guessed / refuted": f"{r['claims']['observed']} / {r['claims']['inferred']} / {r['claims']['refuted']}",
            "Best adopted score": best, "Versions gated": len(r["versions"]),
            "Blocked by the gate": sum(v["status"] == "ROLLED_BACK" for v in r["versions"]),
            "Bounties confirmed on chain": r["verified_bounties"]}
    for c in check["checks"]:
        rows[("PASS " if c["ok"] else "FAIL ") + c["name"]] = c["detail"]
    return cards.detail("Proof receipt: " + ("all checks pass" if check["ok"] else "a check FAILED"), rows=rows,
                        ctas=[cards.cta("Check it again", "receipt"), cards.cta("Status", "status")],
                        narration="Anyone can re-run these checks: the id is a sha256 of the contents, and the seal is a public dorado-1 transaction.")
