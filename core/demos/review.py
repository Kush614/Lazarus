"""Two demos over real evidence:

ACQUISITION  An inherited service (the relic: a binary with no source and no team). Gemini
             writes a due-diligence brief from the ledger, citing only OBSERVED claims as
             fact; SubQ answers "is it safe to retire the original yet?".
AUDIT        Bundles the evidence of a run (the banking run, or the relic's receipt), hashes it,
             has Gemini write an auditor's memo, asks SubQ whether the evidence supports
             sign-off, then anchors the hash in a new Fetch testnet transaction and reads it
             back from the chain to prove it landed.
"""
import hashlib
import json
import threading
import time
import uuid

from pydantic import BaseModel

from core import anchor, gemini, receipt, subq
from core.meta import MetaError, spark


class Markdown(BaseModel):
    markdown: str


def write(call: str, prompt: str) -> tuple[str, str]:
    """Gemini leads; if it is rate-limited or down, Muse Spark writes it. Returns (text, model that wrote it)."""
    try:
        return gemini.ask(call, prompt, chain=gemini.LEAD)
    except gemini.GeminiError:
        try:
            return spark(call, "Follow the user's instructions exactly. Put the whole answer in `markdown`.", prompt, Markdown).markdown, "muse-spark-1.3"
        except MetaError as e:
            raise RuntimeError(f"Gemini and Muse Spark both failed: {e}")


def _canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), default=str)


class Job:
    def __init__(self, db, module: str):
        self.db, self.id = db, f"{module[:5]}-" + uuid.uuid4().hex[:8]
        db.demo_runs.insert_one({"run_id": self.id, "module": module, "status": "running", "steps": [], "started_at": time.time()})

    def step(self, name, status, **data):
        self.db.demo_runs.update_one({"run_id": self.id}, {"$push": {"steps": {"name": name, "status": status, "at": time.time(), **data}},
                                                          "$set": {"current": name}})

    def finish(self, **data):
        self.db.demo_runs.update_one({"run_id": self.id}, {"$set": {"status": "done", "finished_at": time.time(), **data}})

    def run(self, fn):
        def go():
            try:
                fn(self)
            except Exception as e:  # shown on the run, never swallowed
                self.db.demo_runs.update_one({"run_id": self.id}, {"$set": {"status": "failed", "error": f"{type(e).__name__}: {str(e)[:300]}"}})
        threading.Thread(target=go, daemon=True).start()
        return self.id


def _ledger(db) -> dict:
    claims = [{k: v for k, v in d.items() if k in ("id", "endpoint", "claim", "status", "evidence", "confidence")} for d in db.hypotheses.find().sort("id", 1)]
    versions = [{"version": d["version"], "score": round(d["heldout_equivalence"], 4), "status": d["status"],
                 "regressions": len(d.get("regressions", [])), "reason": d.get("reason")} for d in db.port_versions.find().sort("version", 1)]
    divs = [{"id": d["id"], "request": f"{d['input']['method']} {d['input']['path']}", "port_version": d["port_version"],
             "found_by": d["found_by"]} for d in db.divergences.find().sort("id", 1)]
    return {"claims": claims, "versions": versions, "divergences": divs, "probes": db.traces.count_documents({"origin": "probe"})}


def acquisition(db) -> str:
    def work(j: Job):
        led = _ledger(db)
        counts = {s: sum(1 for c in led["claims"] if c["status"] == s) for s in ("OBSERVED", "INFERRED", "REFUTED")}
        j.step("inventory", "done", probes=led["probes"], claims=counts, versions=led["versions"], divergences=len(led["divergences"]),
               note="Everything below comes from probing the running binary. Nobody read its source.")
        prompt = ("You are doing technical due diligence on a service a company just acquired. Its source and team are gone; "
                  "all knowledge comes from probing the running binary. Using ONLY the ledger below, write a brief with these "
                  "markdown sections: 'What it does' (facts: cite OBSERVED claim ids only), 'What we only suspect' (INFERRED ids), "
                  "'What turned out wrong' (REFUTED ids), 'Replacement status' (port versions and scores), 'Top 3 risks', "
                  "'Next 3 actions'. Under 300 words. Never invent behaviour, numbers or ids.\n\nLEDGER:\n" + _canon(led)[:60000])
        text, model = write("acq_brief", prompt)
        j.step("brief", "done", model=model, markdown=text)
        best = max((v["score"] for v in led["versions"] if v["status"] == "ADOPTED"), default=0.0)
        state = _canon({"best_adopted_score": best, "claims": counts, "open_divergences": len(led["divergences"]), "versions": led["versions"]})
        try:
            p = subq.yes_probability(state, "Is it safe to switch off the original service and run only the replacement now?",
                                     "The adopted replacement matches the original on at least 99% of sealed tests and no differences are open.",
                                     "Coverage is below 99%, differences are open, or most behaviour is still unproven.", call="subq_retire")
            j.step("decision", "done", subq_safe_to_retire=round(p, 4), best_adopted_score=best)
        except subq.SubQError as e:
            j.step("decision", "failed", error=str(e))
        j.finish()
    return Job(db, "acquisition").run(work)


def audit(db, banking_run_id: str | None = None) -> str:
    def work(j: Job):
        bank = db.demo_runs.find_one({"run_id": banking_run_id} if banking_run_id else {"module": "banking", "status": "done"},
                                     sort=[("finished_at", -1)])
        relic = receipt.build(db)
        bundle = {"relic_receipt": relic}
        if bank:
            gates = [s for s in bank["steps"] if s["name"] == "gate"]
            bundle["banking"] = {"run_id": bank["run_id"], "target": next((s.get("target") for s in bank["steps"] if s["name"] == "seal"), None),
                                 "sealed_sha256": bank.get("sealed_sha256"), "best_score": bank.get("best_score"),
                                 "gates": [{k: g.get(k) for k in ("version", "matched", "total", "score", "regressions", "status")} for g in gates]}
        sha = hashlib.sha256(_canon(bundle).encode()).hexdigest()
        j.step("bundle", "done", sha256=sha, includes=list(bundle), note="Evidence is hashed first; the memo and the anchor refer to this hash.")
        prompt = ("You are an independent software auditor. A team replaced a legacy system and claims the replacement behaves "
                  "the same. Using ONLY this evidence bundle, write an audit memo in markdown: 'Scope', 'Method' (sealed tests "
                  "hashed before the build; independent comparison; no-regression gate), 'Findings' (cite exact numbers), "
                  "'Limitations', 'Opinion' (one of: unqualified, qualified, adverse, with one sentence why). Under 280 words. "
                  f"Evidence sha256: {sha}.\n\nEVIDENCE:\n" + _canon(bundle)[:40000])
        text, model = write("audit_memo", prompt)
        j.step("memo", "done", model=model, markdown=text)
        try:
            p = subq.yes_probability(_canon(bundle)[:5500], "Does this evidence support signing off that the replacement behaves the same as the original?",
                                     "Sealed tests were fixed before the build, the best adopted version matched them fully or nearly fully, and nothing regressed.",
                                     "Scores are low, regressions exist, or the evidence is missing or unverifiable.", call="subq_signoff")
            j.step("signoff", "done", subq_supports_signoff=round(p, 4))
        except subq.SubQError as e:
            j.step("signoff", "failed", error=str(e))
        a = anchor.anchor("evidence", sha)
        if not a:
            j.step("anchor", "failed", error="the Fetch testnet did not confirm the transaction")
            j.finish(evidence_sha256=sha)
            return
        j.step("anchor", "done", **a)
        memo, when = None, None
        for _ in range(8):  # the REST index can lag the block by a few seconds
            memo, when = receipt._chain_memo(a["tx_hash"])
            if memo:
                break
            time.sleep(3)
        ok = bool(memo) and sha in memo
        j.step("verify", "passed" if ok else "failed", chain_memo=memo, block_time=when,
               detail="Read back from dorado-1: the memo carries this evidence hash." if ok else "Could not read the memo back yet.")
        j.finish(evidence_sha256=sha, tx_hash=a["tx_hash"])
    return Job(db, "audit").run(work)
