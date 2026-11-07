"""lazarus-digger: the ASI:One entry agent. Forms claims, diagnoses, owns strategy.md."""
import asyncio
import json
import os
import pathlib
import subprocess
import sys

from dotenv import load_dotenv
from fetch_hackkit import HackAgent, cards
from fetch_hackkit.peers import ask_agent
from pydantic import BaseModel

from agents.digger import dig as digmod
from agents.digger.cards import decided_card, dig_card, ledger_card, resurrection_card, reveal_card, version_review
from core import ledger
from core.meta import MetaError, spark
from core.schemas import Divergence, Hypothesis, PortVersion, Probe, Request, StrategyEdit, Trace

ROOT = pathlib.Path(__file__).parent.parent.parent
HERE = pathlib.Path(__file__).parent
STRATEGY = HERE / "strategy.md"
ACCESS_LOG = ROOT / "relic" / "logs" / "access.log"
load_dotenv(ROOT / ".env")

agent = HackAgent(
    "LAZARUS Digger", seed=os.environ["AGENT_SEED_PHRASE_DIGGER"], port=8001, handle="lazarus-digger",
    description="Software archaeology: reverse engineer a binary with no source, port legacy code, and prove behavioral "
                "equivalence. Every claim is tagged OBSERVED with a trace or INFERRED with a confidence. Say: exhume <image>.",
    readme_path=str(HERE / "README.md"))
db = ledger.connect()


class Diagnosis(BaseModel):
    root_cause: str
    new_claim: str
    edit: StrategyEdit


def prompt(name: str) -> str:
    return (HERE / "prompts" / f"{name}.md").read_text()


def strategy_version() -> int:
    return db.strategy_versions.count_documents({}) + 1


async def oracle(cmd: dict, timeout=300) -> dict:
    reply = json.loads(await ask_agent(CTX["ctx"], "@lazarus-oracle", json.dumps(cmd), timeout=timeout))
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return reply


async def prober(cmd: dict, timeout=900) -> dict:
    reply = json.loads(await ask_agent(CTX["ctx"], "@lazarus-prober", json.dumps(cmd), timeout=timeout))
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return reply


CTX: dict = {}


async def _design(h: Hypothesis) -> list[Probe]:
    r = await prober({"cmd": "design_probes", "hypothesis": h.model_dump(), "strategy": STRATEGY.read_text()})
    return [Probe(**p) for p in r["probes"]]


async def _run(req: Request) -> Trace | None:
    r = await oracle({"cmd": "run", "request": req.model_dump()})
    return Trace(**r["trace"]) if r["trace"] else None


async def _interpret(h: Hypothesis, p: Probe, t: Trace) -> digmod.Verdict:
    payload = json.dumps({"claim": h.claim, "request": t.request.model_dump(), "prediction": p.prediction, "response": t.response.model_dump()})
    return await asyncio.to_thread(spark, "interpret", prompt("interpret"), payload, digmod.Verdict)


def _all_hypotheses() -> list[Hypothesis]:
    return [Hypothesis(**{k: v for k, v in d.items() if k != "_id"}) for d in db.hypotheses.find().sort("id", 1)]


def _next_version() -> int:
    last = db.port_versions.find_one(sort=[("version", -1)])
    return last["version"] + 1 if last else 1


async def exhume(ctx, msg):
    if db.seal.find_one({"revealed": True}):
        return "FAILED: the source has been revealed, so a new dig would not be blind."
    await agent.reply(ctx, msg.sender, "Digging. Reading the logs, then probing the binary. This takes a few minutes.")
    drafts = await asyncio.to_thread(spark, "initial_dig", prompt("initial_dig"),
                                     f"STRATEGY:\n{STRATEGY.read_text()}\n\nACCESS LOG:\n{ACCESS_LOG.read_text()}", digmod.HypothesisList)
    digmod.store_initial(db, drafts.hypotheses, strategy_version())
    return dig_card(await digmod.dig(db, _design, _run, _interpret), strategy_version())


async def resurrect(ctx, msg):
    await agent.reply(ctx, msg.sender, "Writing the port from OBSERVED claims only, then running the sealed gate.")
    hs = _all_hypotheses()
    version = _next_version()
    traces = [{k: v for k, v in t.items() if k != "_id"} for t in db.traces.find({"id": {"$in": [e for h in hs for e in h.evidence]}})]
    await prober({"cmd": "write_port", "observed": [h.model_dump() for h in hs if h.status == "OBSERVED"],
                  "inferred": [h.model_dump() for h in hs if h.status == "INFERRED"], "traces": traces})
    r = await oracle({"cmd": "gate", "version": version})
    return resurrection_card(PortVersion(**r["version"]))


async def on_divergence(ctx, divergence_id: str):
    """Hunter proved us wrong: diagnose, improve the method, re-dig, patch, gate, then ask the operator."""
    doc = db.divergences.find_one({"id": divergence_id})
    d = Divergence(**{k: v for k, v in doc.items() if k in Divergence.model_fields})
    related = [h.model_dump() for h in _all_hypotheses() if d.input.path.split("/")[1] in h.endpoint]
    dx = await asyncio.to_thread(spark, "diagnose", prompt("diagnose"), json.dumps(
        {"divergence": d.model_dump(), "related": related, "strategy": STRATEGY.read_text()}), Diagnosis)
    old = STRATEGY.read_text()
    new_text = await prober({"cmd": "apply_strategy_diff", "strategy": old, "diff": dx.edit.diff})
    STRATEGY.write_text(new_text["strategy"])
    db.strategy_versions.insert_one({"version": strategy_version(), "edit": dx.edit.model_dump(), "from_divergence": d.id})
    endpoint = f"{d.input.method} {d.input.path.split('?')[0]}"
    h = Hypothesis(id=ledger.next_id(db, "H"), endpoint=endpoint, claim=dx.new_claim, status="INFERRED", confidence=0.8,
                   source="hunt", created_version=strategy_version())
    db.hypotheses.insert_one(h.model_dump())
    for ep in dx.edit.affected_endpoints or [endpoint]:
        await digmod.dig(db, _design, _run, _interpret, max_probes=12, endpoint=ep)
    hs = _all_hypotheses()
    await prober({"cmd": "patch_port", "observed": [x.model_dump() for x in hs if x.status == "OBSERVED"],
                  "divergence": d.model_dump()})
    r = await oracle({"cmd": "gate", "version": _next_version()})
    v = PortVersion(**r["version"])
    op = db.seal.find_one({"_id": "operator"})
    parent = db.port_versions.find_one({"version": v.parent})
    if op:
        await agent.reply(ctx, op["address"], version_review(v, parent["heldout_equivalence"] if parent else None, dx.edit.rationale))


async def reveal(ctx, msg):
    proc = await asyncio.to_thread(subprocess.run, [sys.executable, str(ROOT / "scripts/reveal.py"), "--json"], capture_output=True, text=True, cwd=ROOT)
    if proc.returncode:
        return f"FAILED: reveal did not complete. {proc.stderr[-300:]}"
    db.seal.update_one({"_id": "state"}, {"$set": {"revealed": True}}, upsert=True)
    return reveal_card(json.loads(proc.stdout))


@agent.on_action("show_dig")
async def _show(ctx, msg, sel):
    return ledger_card(_all_hypotheses())


async def guarded(ctx, msg, fn):
    CTX["ctx"] = ctx
    db.seal.update_one({"_id": "operator"}, {"$set": {"address": msg.sender}}, upsert=True)
    try:
        return await fn(ctx, msg)
    except (MetaError, RuntimeError, ValueError, KeyError) as e:
        db.failures.insert_one({"kind": fn.__name__, "error": f"{type(e).__name__}: {e}"})
        return f"FAILED: {fn.__name__} did not complete ({type(e).__name__}: {str(e)[:200]})."


@agent.on_action("resurrect")
async def _res(ctx, msg, sel):
    return await guarded(ctx, msg, resurrect)


@agent.on_action("decide")
async def _decide(ctx, msg, sel):
    CTX["ctx"] = ctx
    r = await oracle({"cmd": "decide", "version": int(sel["version"]), "approved": bool(sel["approved"]), "decided_by": "user"})
    return decided_card(PortVersion(**r["version"]))


@agent.on_action("probe_this")
async def _probe_this(ctx, msg, sel):
    CTX["ctx"] = ctx
    hd = db.hypotheses.find_one({"id": sel["id"]})
    h = Hypothesis(**{k: v for k, v in hd.items() if k != "_id"})
    db.hypotheses.update_one({"id": h.id}, {"$set": {"status": "INFERRED", "confidence": h.confidence or 0.5}})
    await digmod.dig(db, _design, _run, _interpret, max_probes=3, endpoint=h.endpoint)
    return ledger_card([x for x in _all_hypotheses() if x.endpoint == h.endpoint])


@agent.on_text
async def on_text(ctx, msg):
    text = msg.text.strip()
    if text.startswith('{"cmd"'):
        cmd = json.loads(text)
        if cmd["cmd"] == "divergence":
            CTX["ctx"] = ctx
            try:
                await on_divergence(ctx, cmd["id"])
            except Exception as e:
                db.failures.insert_one({"kind": "on_divergence", "error": f"{type(e).__name__}: {e}"})
        return None
    low = text.lower()
    if low.startswith("exhume"):
        return await guarded(ctx, msg, exhume)
    if "show the dig" in low:
        return ledger_card(_all_hypotheses())
    if low.startswith("resurrect"):
        return await guarded(ctx, msg, resurrect)
    if low.startswith("reveal"):
        return await guarded(ctx, msg, reveal)
    if low.startswith("hunt"):
        return "Hunts go to the independent oracle, which holds the money: message @lazarus-oracle with `Hunt <input>`."
    return cards.detail("LAZARUS", rows={"What this does": "Raises dead software. Give me a binary with no source; I dig, port it, and pay anyone who proves the port wrong."},
                        ctas=[cards.cta("Show the dig", "show_dig"), cards.cta("Resurrect", "resurrect")], narration="Say `Exhume <image>` to start a dig.")


if __name__ == "__main__":
    agent.run()
