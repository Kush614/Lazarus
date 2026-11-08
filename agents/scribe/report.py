"""The evidence document: what was observed, what was only inferred, and how the system changed.
Built only from records, with no model in the loop, so it cannot embellish them. The same
records always give the same hash, which is what makes the report checkable."""
import hashlib
import json
import pathlib

from pydantic import BaseModel


class Report(BaseModel):
    markdown: str
    sha256: str
    observed: int
    inferred: int
    refuted: int
    versions: int
    best_score: float | None


def _seal(root: pathlib.Path) -> dict:
    try:
        return json.loads((root / "SEAL.json").read_text())
    except (OSError, ValueError):
        return {}


def build(db, root: pathlib.Path) -> Report:
    hs = list(db.hypotheses.find().sort("id", 1))
    by = {s: [h for h in hs if h["status"] == s] for s in ("OBSERVED", "INFERRED", "REFUTED")}
    versions = list(db.port_versions.find().sort("version", 1))
    edits = list(db.strategy_versions.find().sort("version", 1))
    divs = list(db.divergences.find().sort("id", 1))
    pays = list(db.payments.find().sort("tx_hash", 1))
    seal = _seal(root)
    lines = ["# LAZARUS evidence report", ""]
    if seal:
        lines += ["## Seal", *[f"- {k}: `{v}`" for k, v in sorted(seal.items()) if isinstance(v, str | int)], ""]
    lines += ["## Observed", "Each of these has a recorded trace behind it.", ""]
    lines += [f"- **{h['id']}** `{h['endpoint']}` {h['claim']} (traces: {', '.join(h['evidence'])})" for h in by["OBSERVED"]] or ["- none"]
    lines += ["", "## Inferred", "These are guesses. No probe has settled them, so do not rely on them.", ""]
    lines += [f"- **{h['id']}** `{h['endpoint']}` {h['claim']} (confidence {h.get('confidence', 0):.2f})" for h in by["INFERRED"]] or ["- none"]
    lines += ["", "## Refuted", "These were believed, then disproved by a trace.", ""]
    lines += [f"- **{h['id']}** `{h['endpoint']}` {h['claim']} (traces: {', '.join(h['evidence'])})" for h in by["REFUTED"]] or ["- none"]
    lines += ["", "## Port versions", "Scores are on sealed tests no agent can read.", "", "| Version | Score | Regressions | Status | Decided by |", "|---|---|---|---|---|"]
    lines += [f"| v{v['version']} | {v['heldout_equivalence']:.1%} | {len(v.get('regressions') or [])} | {v['status']} | {v.get('decided_by') or '-'} |" for v in versions]
    lines += ["", "## How the method improved", ""]
    lines += [f"- Strategy v{e['version']}, from {e.get('from_divergence', 'unknown')}: {e['edit']['rationale']}" for e in edits] or ["- no changes yet"]
    lines += ["", "## Divergences", ""]
    lines += [f"- **{d['id']}** on port v{d['port_version']}, {d['input']['method']} {d['input']['path']}, bounty tx: {d.get('tx_bounty') or 'none'}" for d in divs] or ["- none found"]
    lines += ["", "## Verified payments", "Only transfers the chain confirmed are recorded here.", ""]
    lines += [f"- {p['kind']}: {p['amount_fet']} testnet FET, `{p['tx_hash']}`" for p in pays] or ["- none"]
    lines += ["", f"Failures logged during this run: {db.failures.count_documents({})}"]
    body = "\n".join(lines)
    adopted = [v["heldout_equivalence"] for v in versions if v["status"] == "ADOPTED"]
    return Report(markdown=body, sha256=hashlib.sha256(body.encode()).hexdigest(), observed=len(by["OBSERVED"]), inferred=len(by["INFERRED"]),
                  refuted=len(by["REFUTED"]), versions=len(versions), best_score=max(adopted) if adopted else None)
