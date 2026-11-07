"""The dig loop, with brains and transport injected so it can be tested offline.

The model judges; code holds the evidence. Trace ids come from what the oracle actually
returned, so nothing can be tagged OBSERVED without a real trace.
"""
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel

from core import ledger
from core.schemas import Hypothesis, Probe, Request, Trace


class Verdict(BaseModel):
    status: Literal["INFERRED", "OBSERVED", "REFUTED"]
    confidence: float | None = None
    corrected_claim: str | None = None


class HypothesisList(BaseModel):
    hypotheses: list[Hypothesis]


def store_initial(db, drafts: list[Hypothesis], version: int) -> list[Hypothesis]:
    """Everything starts INFERRED. The log suggests; only a probe proves."""
    out = []
    for h in drafts:
        h = h.model_copy(update={"id": ledger.next_id(db, "H"), "status": "INFERRED", "evidence": [], "source": "log",
                                 "confidence": h.confidence if h.confidence is not None else 0.5, "created_version": version})
        db.hypotheses.insert_one(h.model_dump())
        out.append(h)
    return out


def apply_verdict(db, h: Hypothesis, v: Verdict, trace: Trace) -> Hypothesis:
    update = {"status": v.status, "confidence": v.confidence if v.status == "INFERRED" else None, "source": "probe"}
    if v.status == "INFERRED" and v.confidence is None:
        update["confidence"] = h.confidence
    if v.status != "INFERRED":
        update["evidence"] = [*h.evidence, trace.id]
    if v.corrected_claim and v.status == "REFUTED":
        # Keep the refuted claim on the ledger; the correction is a new claim to be probed.
        new = Hypothesis(id=ledger.next_id(db, "H"), endpoint=h.endpoint, claim=v.corrected_claim, status="INFERRED",
                         confidence=0.7, source="probe", created_version=h.created_version)
        db.hypotheses.insert_one(new.model_dump())
    new_h = h.model_copy(update=update)
    Hypothesis(**new_h.model_dump())  # revalidate the honesty rules
    db.hypotheses.update_one({"id": h.id}, {"$set": update})
    return new_h


async def dig(db, design: Callable[[Hypothesis], Awaitable[list[Probe]]],
              run: Callable[[Request], Awaitable[Trace | None]],
              interpret: Callable[[Hypothesis, Probe, Trace], Awaitable[Verdict]],
              max_probes: int = 40, endpoint: str | None = None, progress=None) -> dict:
    """Probes INFERRED claims until the budget runs out or a full pass settles nothing."""
    used = 0
    tried: set[str] = set()
    while used < max_probes:
        query = {"status": "INFERRED", **({"endpoint": endpoint} if endpoint else {})}
        todo = [Hypothesis(**{k: v for k, v in d.items() if k != "_id"}) for d in db.hypotheses.find(query) if d["id"] not in tried]
        if not todo:
            break
        for h in todo:
            if used >= max_probes:
                break
            tried.add(h.id)
            for p in await design(h):
                if used >= max_probes:
                    break
                p = p.model_copy(update={"id": ledger.next_id(db, "P"), "hypothesis_id": h.id})
                db.probes.insert_one(p.model_dump())
                used += 1
                t = await run(p.request)
                if t is None:
                    continue  # FAILED probe: the claim stays INFERRED, logged by the oracle
                h = apply_verdict(db, h, await interpret(h, p, t), t)
                if h.status != "INFERRED":
                    break
            if progress:
                await progress(used)
    return stats(db, used)


def stats(db, probes: int | None = None) -> dict:
    count = lambda s: db.hypotheses.count_documents({"status": s})
    obs, inf, ref = count("OBSERVED"), count("INFERRED"), count("REFUTED")
    total = obs + inf + ref
    return {"endpoints": sorted(db.hypotheses.distinct("endpoint")), "OBSERVED": obs, "INFERRED": inf, "REFUTED": ref,
            "resolved_pct": round(100 * (obs + ref) / total) if total else 0,
            "probes": probes if probes is not None else db.probes.count_documents({})}
