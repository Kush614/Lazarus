"""lazarus-scout: attacks each adopted port with edge-case inputs before a paying hunter does.
It goes through the oracle, so it sees the same black box a hunter sees and no sealed test."""
import json
import os
import pathlib

from dotenv import load_dotenv
from fetch_hackkit import HackAgent, cards, text_message
from fetch_hackkit.peers import PeerError, ask_agent

from agents.scout.mutate import plan, request_hash
from core import ledger
from core.schemas import Request
from core.trust import address_of, is_command, is_peer

ROOT = pathlib.Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")
BUDGET = 30
WATCH_SECONDS = 300.0

agent = HackAgent(
    "LAZARUS Scout", seed=os.environ["AGENT_SEED_PHRASE_SCOUT"], port=8005, handle="lazarus-scout",
    description="Differential tester for software ports: fires edge-case inputs at the original and the port, and reports every difference with the input that reproduces it.",
    readme_path=str(ROOT / "agents/scout/README.md"))
db = ledger.connect()


async def run_scout(ctx, compare=None) -> dict:
    """Stops early and reports honestly if the oracle stops answering. `compare` is injectable for tests."""
    async def default(req: Request) -> dict:
        return json.loads(await ask_agent(ctx, address_of("oracle"), json.dumps({"cmd": "compare", "request": req.model_dump()}), timeout=60))

    compare = compare or default
    adopted = ledger.latest_adopted(db)
    if not adopted:
        return {"version": None, "tried": 0, "found": [], "reason": "No port has been adopted yet."}
    version = adopted["version"]
    traces = [Request(**t["request"]) for t in db.traces.find({"target": "original"})]
    weak = db.hypotheses.distinct("endpoint", {"status": "INFERRED"})
    seen = {d["hash"] for d in db.scout_seen.find({"version": version})}
    found, tried, failed = [], 0, None
    for req, label in plan(traces, weak, seen, BUDGET):
        try:
            r = await compare(req)
        except (PeerError, ValueError, TimeoutError) as e:
            failed = f"{type(e).__name__}: {str(e)[:120]}"
            db.failures.insert_one({"kind": "scout_compare", "error": failed})
            break
        if "error" in r:
            failed = str(r["error"])[:120]
            db.failures.insert_one({"kind": "scout_compare", "error": failed})
            break
        tried += 1
        db.scout_seen.insert_one({"version": version, "hash": request_hash(req)})
        if r.get("diverged") and r.get("divergence_id"):
            found.append({"id": r["divergence_id"], "what": label, "path": f"{req.method} {req.path}"})
    summary = {"version": version, "tried": tried, "found": found, "reason": failed}
    db.scout_runs.insert_one({**summary})
    summary.pop("_id", None)
    return summary


def result_card(s: dict):
    if s["version"] is None:
        return cards.info("Nothing to test yet", rows={"Why": s["reason"]})
    rows = {"Port version": s["version"], "Inputs tried": s["tried"], "Differences found": len(s["found"])}
    if s["reason"]:
        rows["Stopped early"] = s["reason"]
    if not s["found"]:
        return cards.detail("Scout: no differences", rows=rows, ctas=[cards.cta("Run again", "scout_run")],
                            narration="None of these inputs told them apart. That is evidence, not proof.")
    items = [cards.item(f["id"], f["what"], action="improve", cta_label="Improve from this", subtitle=f'{f["id"]} · {f["path"]}',
                        badges=[cards.badge("DIVERGED", "danger")]) for f in s["found"][:12]]
    return cards.carousel(f'Scout found {len(s["found"])} difference(s) in port v{s["version"]}', items, subtitle=f'{s["tried"]} inputs tried',
                          narration="Each one has an input that reproduces it. Pick one to send into the improvement loop.")


@agent.on_action("scout_run")
async def _run(ctx, msg, sel):
    return result_card(await run_scout(ctx))


@agent.on_action("improve")
async def _improve(ctx, msg, sel):
    await ctx.send(address_of("digger"), text_message(json.dumps({"cmd": "divergence", "id": sel["id"]})))
    return f'Sent {sel["id"]} to @lazarus-digger. It will diagnose it, patch the port, run the gate, and ask you to review the result.'


@agent.on_interval(period=WATCH_SECONDS)
async def watch(ctx):
    """A new adopted version gets tested without being asked, for as long as this agent runs."""
    adopted = ledger.latest_adopted(db)
    if not adopted or db.scout_runs.find_one({"version": adopted["version"]}):
        return
    try:
        s = await run_scout(ctx)
    except Exception as e:
        db.failures.insert_one({"kind": "scout_watch", "error": f"{type(e).__name__}: {e}"})
        return
    op = db.seal.find_one({"_id": "operator"})
    if op and s["found"]:
        await agent.reply(ctx, op["address"], result_card(s))


@agent.on_text
async def on_text(ctx, msg):
    text = msg.text.strip()
    if is_command(text):
        if not is_peer(msg.sender):
            return "Internal commands are only accepted from LAZARUS agents."
        try:
            return json.dumps(await run_scout(ctx))
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"})
    return result_card(await run_scout(ctx))


if __name__ == "__main__":
    agent.run()
