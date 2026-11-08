"""lazarus-digger: the ASI:One entry agent. Forms claims, diagnoses, owns strategy.md."""
import asyncio
import json
import os
import pathlib
import subprocess
import sys

from dotenv import load_dotenv
from fetch_hackkit import ASI1, ASI1Error, HackAgent
from fetch_hackkit.peers import PeerError, ask_agent
from pydantic import BaseModel

from agents.digger import dig as digmod
from agents.digger.cards import (blocked_card, receipt_card, decided_card, dig_card, failure_card, help_card, ledger_card, resurrection_card, reveal_card, reveal_review,
                                 status_card, use_case_card, use_cases_card, version_review)
from core import ledger
from core import receipt as receipt_mod
from core.meta import MetaError, spark
from core.intent import route
from core.schemas import Divergence, Hypothesis, PortVersion, Probe, Request, StrategyEdit, Trace
from core.trust import address_of, is_command, is_peer

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


async def _peer(role: str, cmd: dict, timeout: int, attempts: int = 1) -> dict:
    """`attempts` above 1 is only for commands that are safe to repeat if a reply got lost."""
    for attempt in range(attempts):
        try:
            reply = json.loads(await ask_agent(CTX["ctx"], address_of(role), json.dumps(cmd), timeout=timeout))
            break
        except PeerError:
            if attempt == attempts - 1:
                raise
            await asyncio.sleep(2 * (attempt + 1))
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return reply


async def oracle(cmd: dict, timeout=300) -> dict:
    return await _peer("oracle", cmd, timeout, attempts=3 if cmd["cmd"] == "run" else 1)


async def prober(cmd: dict, timeout=900) -> dict:
    return await _peer("prober", cmd, timeout, attempts=3 if cmd["cmd"] == "design_probes" else 1)


async def sentinel_clears(version: int):
    """Returns a blocked card if the sentinel refuses, after discarding the code. None means go ahead."""
    verdict = await _peer("sentinel", {"cmd": "review"}, 60, attempts=3)
    if verdict["passed"]:
        return None
    db.failures.insert_one({"kind": "sentinel_blocked", "version": version, "findings": verdict["findings"]})
    await prober({"cmd": "restore_port"})
    return blocked_card(version, verdict["findings"])


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
    blocked = await sentinel_clears(version)
    if blocked:
        return blocked
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
    op = db.seal.find_one({"_id": "operator"})
    blocked = await sentinel_clears(_next_version())
    if blocked:
        if op:
            await agent.reply(ctx, op["address"], blocked)
        return
    r = await oracle({"cmd": "gate", "version": _next_version()})
    v = PortVersion(**r["version"])
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
    except (MetaError, RuntimeError, ValueError, KeyError, TimeoutError) as e:
        db.failures.insert_one({"kind": fn.__name__, "error": f"{type(e).__name__}: {e}"})
        return failure_card(fn.__name__, f"{type(e).__name__}: {str(e)[:200]}", fn.__name__)


def _llm():
    try:
        return ASI1()
    except ASI1Error:
        return None  # No key: routing runs on rules alone.


def status():
    s = digmod.stats(db)
    return status_card(s, ledger.latest_adopted(db), db.divergences.count_documents({}), db.divergences.count_documents({"found_by": "lazarus-scout"}), db.failures.count_documents({}))


def pointer(handle: str, what: str) -> str:
    return f"{what} Message @{handle} here in ASI:One."


def receipt():
    r = receipt_mod.build(db, ROOT)
    db.receipts.update_one({"id": r["id"]}, {"$setOnInsert": r}, upsert=True)
    return receipt_card(r, receipt_mod.verify(r))


@agent.on_action("receipt")
async def _receipt(ctx, msg, sel):
    return await asyncio.to_thread(receipt)


@agent.on_action("exhume")
async def _exh(ctx, msg, sel):
    return await guarded(ctx, msg, exhume)


@agent.on_action("reveal")
async def _rev(ctx, msg, sel):
    return await guarded(ctx, msg, reveal)


@agent.on_action("status")
async def _status(ctx, msg, sel):
    return status()


@agent.on_action("use_cases")
async def _uses(ctx, msg, sel):
    return use_cases_card()


@agent.on_action("use_case")
async def _use(ctx, msg, sel):
    return use_case_card(str(sel.get("id")))


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


# ---- LAZARUS Studio inside ASI:One (the console's Studio flow, as cards with buttons) ----
from agents.factory import gateway as gw  # noqa: E402


@agent.on_action("gw_home")
async def _gw_home(ctx, msg, sel):
    return gw.home(db)


@agent.on_action("gw_browse")
async def _gw_browse(ctx, msg, sel):
    return gw.browse(db, int(sel.get("page") or 0))


@agent.on_action("gw_biz")
async def _gw_biz(ctx, msg, sel):
    return gw.business(db, str(sel.get("id")))


@agent.on_action("gw_buy")
async def _gw_buy(ctx, msg, sel):
    return await gw.buy(db, str(sel.get("id")), int(sel.get("i") or 0))


@agent.on_action("gw_verify")
async def _gw_verify(ctx, msg, sel):
    return await gw.verify(db, str(sel.get("id")))


@agent.on_action("gw_market")
async def _gw_market(ctx, msg, sel):
    return gw.market_round(db)


@agent.on_action("gw_trades")
async def _gw_trades(ctx, msg, sel):
    return gw.trades(db)


@agent.on_action("gw_start_help")
async def _gw_start(ctx, msg, sel):
    return gw.start(db, "")


@agent.on_text
async def on_text(ctx, msg):
    text = msg.text.strip()
    if is_command(text):
        if not is_peer(msg.sender):
            return "Internal commands are only accepted from LAZARUS agents."
        cmd = json.loads(text)
        if cmd["cmd"] == "divergence":
            CTX["ctx"] = ctx
            try:
                await on_divergence(ctx, cmd["id"])
            except Exception as e:
                db.failures.insert_one({"kind": "on_divergence", "error": f"{type(e).__name__}: {e}"})
        return None
    if gw.wants(text):
        return await gw.handle_text(db, text)
    intent = await route(text, _llm())
    if intent == "exhume":
        return await guarded(ctx, msg, exhume)
    if intent == "show_dig":
        return ledger_card(_all_hypotheses())
    if intent == "resurrect":
        return await guarded(ctx, msg, resurrect)
    if intent == "reveal":
        return reveal_review()  # Irreversible, and routing can misread words, so it always asks first.
    if intent == "status":
        return status()
    if intent == "use_cases":
        return use_cases_card()
    if intent == "receipt":
        return await asyncio.to_thread(receipt)
    if intent == "challenge":
        return pointer("lazarus-oracle", "Free challenges run on the independent oracle. Say `challenge <input>`, no stake needed.")
    if intent == "hunt":
        return pointer("lazarus-oracle", "Hunts go to the independent oracle, which holds the money. Say `Hunt <input>`.")
    if intent == "scout":
        return pointer("lazarus-scout", "Scout tests the adopted port with edge-case inputs. Say `scout`.")
    if intent == "review":
        return pointer("lazarus-sentinel", "Sentinel reviews generated code. Paste the code.")
    if intent == "report":
        return pointer("lazarus-scribe", "Scribe writes the evidence report. Say `report`.")
    return help_card()


if __name__ == "__main__":
    agent.run()
