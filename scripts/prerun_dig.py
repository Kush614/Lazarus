#!/usr/bin/env python3
"""Runs the whole story for real, in one process, with no agent started or registered.

Spark reads the relic's access log and drafts claims; Muse Code designs probes; the real
binary answers; Spark judges each answer; Muse Code writes the port; the sentinel scans it;
the sealed gate scores it; the scout hunts for differences; Muse Code patches; a seeded
bad patch is gated (and must be blocked); the scribe writes the report.

It uses the same functions the agents call, so the records it leaves in Mongo are the
same records the agents would leave. Nothing here pays anyone: payments need testnet FET.

usage: uv run python scripts/prerun_dig.py [--probes 40] [--fresh]
"""
import argparse
import asyncio
import hashlib
import json
import os
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
# Importing the agents builds HackAgent objects. Without this, a running event loop could
# register them on Agentverse, and going public is the operator's call, not this script's.
os.environ["AGENTVERSE_API_KEY"] = ""
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
os.environ.setdefault("SANDBOX", "process")

from agents.digger import dig as digmod
from agents.prober import agent as prober
from agents.prober.muse_client import run_exec
from agents.scout import agent as scout
from agents.scribe.report import build as build_report
from agents.sentinel.scan import scan_port
from agents.oracle.service import Oracle
from core import ledger
from core.meta import spark
from core.sandbox import original_target, port_target
from core.schemas import Hypothesis, Probe, Request

DIGGER = ROOT / "agents" / "digger"
PORT = ROOT / "port"
EVIDENCE = ROOT / "evidence"
STEPS: list[dict] = []


def say(step: str, **data):
    row = {"at": time.strftime("%H:%M:%S"), "step": step, **data}
    STEPS.append(row)
    print(json.dumps(row), flush=True)


class ContentRepo:
    """Versioning without git: a version's 'commit' is the sha256 of the port's files.
    Rollback restores the copy kept for the last adopted version."""

    def __init__(self, keep: pathlib.Path):
        self.keep = keep

    def _hash(self) -> str:
        h = hashlib.sha256()
        for f in sorted(p for p in PORT.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            h.update(str(f.relative_to(PORT)).encode()); h.update(f.read_bytes())
        return "content:" + h.hexdigest()[:16]

    def propose(self, version: int) -> str:
        return self._hash()

    def adopt(self, version: int, score: float, parent_score) -> str:
        shutil.rmtree(self.keep, ignore_errors=True)
        shutil.copytree(PORT, self.keep, ignore=shutil.ignore_patterns("__pycache__"))
        return self._hash()

    def rollback(self, proposal: str, version: int, score: float, regressions) -> str:
        if self.keep.exists():
            shutil.rmtree(PORT)
            shutil.copytree(self.keep, PORT)
        return self._hash()


def prompt(name: str) -> str:
    return (DIGGER / "prompts" / f"{name}.md").read_text()


def hypotheses(db) -> list[Hypothesis]:
    return [Hypothesis(**{k: v for k, v in d.items() if k != "_id"}) for d in db.hypotheses.find().sort("id", 1)]


def gate_and_decide(db, oracle: Oracle, version: int, label: str):
    verdict = scan_port(PORT)
    if not verdict.passed:
        say("sentinel_blocked", version=version, findings=[f.model_dump() for f in verdict.findings][:5])
        oracle.repo.rollback("", version, 0, [])
        return None
    say("sentinel_passed", version=version)
    v = oracle.gate(version)
    say("gate", version=version, label=label, equivalence=round(v.heldout_equivalence, 4), regressions=v.regressions, reason=v.reason)
    v = oracle.decide(version, approved=True, decided_by="auto")
    say("decision", version=version, status=v.status)
    return v


async def main(args):
    db = ledger.connect()
    if args.fresh:
        for c in db.list_collection_names():
            db[c].delete_many({})
        say("fresh", note="cleared the dig collections")
    keep = ROOT / "logs" / "prerun_adopted_port"
    oracle = Oracle(db, ContentRepo(keep), original_target(), lambda v: port_target(v, str(ROOT)))
    oracle.original.start()
    try:
        # 1. Dig: the log suggests, only a probe proves.
        strategy = (DIGGER / "strategy.md").read_text()
        if db.hypotheses.count_documents({}):
            say("resumed", claims=db.hypotheses.count_documents({}), probes_so_far=db.probes.count_documents({}))
        else:
            log = (ROOT / "relic" / "logs" / "access.log").read_text()
            drafts = await asyncio.to_thread(spark, "initial_dig", prompt("initial_dig"),
                                             f"STRATEGY:\n{strategy}\n\nACCESS LOG:\n{log}", digmod.HypothesisList)
            digmod.store_initial(db, drafts.hypotheses, 1)
            say("drafted", claims=len(drafts.hypotheses), model="muse-spark-1.3")

        async def design(h: Hypothesis) -> list[Probe]:
            r = await asyncio.to_thread(prober.design_probes, {"hypothesis": h.model_dump(), "strategy": strategy})
            return [Probe(**p) for p in r["probes"]]

        async def run(req: Request):
            return await asyncio.to_thread(oracle.run_probe, req)

        async def interpret(h, p, t):
            payload = json.dumps({"claim": h.claim, "request": t.request.model_dump(), "prediction": p.prediction, "response": t.response.model_dump()})
            return await asyncio.to_thread(spark, "interpret", prompt("interpret"), payload, digmod.Verdict)

        async def progress(n):
            say("probing", probes=n)

        stats = await digmod.dig(db, design, run, interpret, max_probes=args.probes, progress=progress)
        say("dug", **stats)

        # 2. Resurrect v1 from OBSERVED claims only.
        hs = hypotheses(db)
        traces = [{k: v for k, v in t.items() if k != "_id"} for t in db.traces.find({"id": {"$in": [e for h in hs for e in h.evidence]}})]
        await asyncio.to_thread(prober.write_port, {"observed": [h.model_dump() for h in hs if h.status == "OBSERVED"],
                                                    "inferred": [h.model_dump() for h in hs if h.status == "INFERRED"], "traces": traces})
        say("port_written", version=1, by="muse-code")
        v1 = gate_and_decide(db, oracle, 1, "first port")

        # 3. Hunt: the scout fires edge cases at the adopted port through the oracle.
        found = []
        if v1 and v1.status == "ADOPTED":
            with port_target(1, str(ROOT)) as pt:
                async def compare(req: Request) -> dict:
                    return await asyncio.to_thread(oracle.compare, req, pt, "scout")
                s = await scout.run_scout(None, compare=compare)
            found = s["found"]
            say("scout", tried=s["tried"], found=len(found), examples=[f["what"] + " " + f["path"] for f in found[:5]])

        # 4. Improve: Muse Code patches from the first difference, then the gate decides.
        if found:
            d = db.divergences.find_one({"id": found[0]["id"]}, {"_id": 0, "input_hash": 0})
            hs = hypotheses(db)
            await asyncio.to_thread(prober.patch_port, {"observed": [h.model_dump() for h in hs if h.status == "OBSERVED"], "divergence": d})
            say("port_patched", version=2, from_divergence=d["id"], by="muse-code")
            gate_and_decide(db, oracle, 2, "patched from a found difference")

        # 5. Seeded bad patch. Generic sabotage, labelled as such; the gate must refuse it.
        nxt = (db.port_versions.find_one(sort=[("version", -1)]) or {"version": 0})["version"] + 1
        _, ws = await asyncio.to_thread(run_exec, "seeded_bad_patch",
                                        "This is a deliberately bad patch for a demo of a safety gate. In app.py, change the service so that "
                                        "every response with a 4xx status is returned with status 200 instead. Change nothing else.",
                                        PORT)
        try:
            prober._sync_port(ws)
        finally:
            shutil.rmtree(ws, ignore_errors=True)
        say("seeded_bad_patch", version=nxt, note="generic sabotage written by Muse Code on request")
        gate_and_decide(db, oracle, nxt, "seeded bad patch")
    finally:
        oracle.original.stop()

    rep = build_report(db, ROOT)
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE / "report.md").write_text(rep.markdown)
    say("report", sha256=rep.sha256)
    (EVIDENCE / "prerun.json").write_text(json.dumps({"steps": STEPS}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--probes", type=int, default=40)
    ap.add_argument("--fresh", action="store_true")
    asyncio.run(main(ap.parse_args()))
