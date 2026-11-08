"""lazarus-oracle: deterministic, independent, holds the money."""
import asyncio
import json
import os
import pathlib

from dotenv import load_dotenv
from fetch_hackkit import HackAgent, text_message
from fetch_hackkit.payments import Paywall
from fetch_hackkit.peers import PeerError, ask_agent

from agents.oracle.cards import challenge_card, challenge_form, hunt_card, hunt_form, stake_review
from agents.oracle.service import Oracle
from core import ledger, payments, sandbox, trust_price
from core.schemas import Request
from core.trust import address_of, is_command, is_peer
from core.versioning import Repo

ROOT = pathlib.Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")


class StakePaywall(Paywall):
    """hackkit does not pass the transaction to the paid handler, and the oracle needs it."""

    async def _on_commit(self, ctx, sender, msg):
        key = f"hackkit:pay:{msg.reference}"
        pending = ctx.storage.get(key) if msg.reference else None
        if isinstance(pending, dict):
            pending["selection"] = {**(pending.get("selection") or {}), "_tx": msg.transaction_id}
            ctx.storage.set(key, pending)
        await super()._on_commit(ctx, sender, msg)


agent = HackAgent(
    "LAZARUS Oracle", seed=os.environ["AGENT_SEED_PHRASE_ORACLE"], port=8003, handle="lazarus-oracle",
    description="Independent behavioral-equivalence oracle and bug bounty for software archaeology: "
                "stake testnet FET, find an input where a resurrected port diverges from the original binary, get paid.",
    readme_path=str(ROOT / "agents/oracle/README.md"))
agent._paywall = StakePaywall(agent)  # must exist before @agent.paid registers products

db = ledger.connect()
original = sandbox.original_target()
service = Oracle(db, Repo(ROOT), original, lambda v: sandbox.port_target(v, str(ROOT)))
port_live = None


def _current_port():
    global port_live
    if port_live is None:
        adopted = ledger.latest_adopted(db)
        port_live = sandbox.port_target(adopted["version"] if adopted else 0, str(ROOT))
        port_live.start()
    return port_live


def _reset_port():
    global port_live
    if port_live is not None:
        port_live.stop()
        port_live = None


@agent.on_event("startup")
async def _boot(ctx):
    await asyncio.to_thread(original.start)
    ctx.logger.info(f"oracle wallet {agent.wallet.address()}")


@agent.on_event("shutdown")
async def _down(ctx):
    original.stop()
    _reset_port()


async def _internal(cmd: dict) -> dict:
    """JSON protocol used by lazarus-digger over ACP."""
    if cmd["cmd"] == "run":
        t = await asyncio.to_thread(service.run_probe, Request(**cmd["request"]))
        return {"trace": t.model_dump() if t else None}
    if cmd["cmd"] == "gate":
        v = await asyncio.to_thread(service.gate, cmd["version"])
        return {"version": v.model_dump()}
    if cmd["cmd"] == "decide":
        v = await asyncio.to_thread(service.decide, cmd["version"], cmd["approved"], cmd["decided_by"])
        _reset_port()
        return {"version": v.model_dump()}
    if cmd["cmd"] == "compare":
        return await asyncio.to_thread(service.compare, Request(**cmd["request"]), _current_port(), "lazarus-scout")
    raise ValueError(f"unknown cmd {cmd['cmd']}")


def _parse_request(raw: str) -> Request | None:
    try:
        return Request(**json.loads(raw))
    except (ValueError, TypeError):
        return None


async def _to_request(ctx, description: str, raw: str) -> Request | str:
    """A Request, or a FAILED message for the user."""
    req = _parse_request(raw) if raw else None
    if req is None and description:
        try:
            answer = await ask_agent(ctx, address_of("prober"), json.dumps({"cmd": "concretize", "description": description}), timeout=180)
            req = Request(**json.loads(answer)["request"])
        except (PeerError, ValueError, KeyError, TypeError) as e:
            return f"FAILED: could not turn that into a concrete request ({type(e).__name__}). Try raw JSON."
    return req or "FAILED: that is not a valid request. Expected JSON with method, path, headers, body."


async def _challenge(ctx, sender: str, description: str, raw: str):
    req = await _to_request(ctx, description, raw)
    if isinstance(req, str):
        return req
    try:
        return challenge_card(await asyncio.to_thread(service.challenge, req, _current_port(), sender))
    except ValueError as e:
        return f"FAILED: {e}. Nothing was recorded."


async def _prepare(ctx, description: str, raw: str):
    req = await _to_request(ctx, description, raw)
    if isinstance(req, str):
        return req
    if await asyncio.to_thread(service.already_claimed, req):
        return "That exact input has already been paid against this port version. No stake taken. Try a different one."
    return stake_review(req, trust_price.offer(db))


@agent.on_text
async def on_text(ctx, msg):
    text = msg.text.strip()
    if is_command(text):
        if not is_peer(msg.sender):
            return "Internal commands are only accepted from LAZARUS agents. Say `Hunt` to start a hunt."
        try:
            return json.dumps(await _internal(json.loads(text)))
        except Exception as e:
            db.failures.insert_one({"kind": "internal", "error": str(e)})
            return json.dumps({"error": f"{type(e).__name__}: {e}"})
    low = text.lower()
    if low.startswith("challenge"):
        rest = text[9:].lstrip(" :")
        if not rest:
            return challenge_form()
        return await _challenge(ctx, msg.sender, "" if rest.startswith("{") else rest, rest if rest.startswith("{") else "")
    if low.startswith("hunt"):
        rest = text[4:].lstrip(" :")
        if not rest:
            return hunt_form()
        return await _prepare(ctx, "" if rest.startswith("{") else rest, rest if rest.startswith("{") else "")
    return hunt_form()


@agent.on_action("hunt_form")
async def _form(ctx, msg, sel):
    return hunt_form()


@agent.on_action("prepare_hunt")
async def _prep(ctx, msg, sel):
    return await _prepare(ctx, sel.get("description") or "", sel.get("raw") or "")


@agent.on_action("challenge_form")
async def _cform(ctx, msg, sel):
    return challenge_form()


@agent.on_action("challenge_run")
async def _crun(ctx, msg, sel):
    return await _challenge(ctx, msg.sender, sel.get("description") or "", sel.get("raw") or "")


@agent.on_action("cancel_hunt")
async def _cancel(ctx, msg, sel):
    return "Hunt cancelled. No stake taken."


@agent.paid("hunt", amount=payments.STAKE_FET, description="Hunt stake")
async def hunt(ctx, msg, sel):
    req = Request(**sel["request"])
    tx = sel["_tx"]
    wallet = str(agent.wallet.address())
    offer = trust_price.offer(db)  # fixed before the hunt: a divergence resets the clock

    def pay(d):
        payer = payments.payer_of(tx)
        return payments.bounty(db, agent.wallet, payer, msg.sender, d.id, bounty_fet=offer) if payer else None

    def go():
        return service.hunt(msg.sender, req, tx, wallet, _current_port(), pay)

    result = await asyncio.to_thread(go)
    if result is None:
        return "FAILED: stake could not be verified on-chain or was already used. Nothing was executed."
    if result.diverged:
        await agent.reply(ctx, msg.sender, hunt_card(result))
        try:
            await ctx.send(address_of("digger"), text_message(json.dumps({"cmd": "divergence", "id": result.divergence_id})))
        except Exception as e:
            db.failures.insert_one({"kind": "notify_digger", "error": str(e)})
        return None
    return hunt_card(result)


if __name__ == "__main__":
    agent.run()
