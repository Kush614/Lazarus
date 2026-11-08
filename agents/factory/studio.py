"""LAZARUS Studio: start a business by describing it in one sentence.

design()  Muse Spark turns the founder's sentence into a spec (catalog, prices, policies). Muse Spark
          The spec is the single source of truth for the business.
answer()  A customer message gets a reply plus a card. The card (catalog, quote, booking, order)
          is computed from the spec by code, so a price on a card can never be invented; the
          sentence around it is written by Muse Spark from the spec only.
verify()  Before customers see it, LAZARUS asks the business questions whose answers are in the
          spec (prices, policies) plus one trap (something it does not offer). Prices are checked
          by code; policies and the trap are graded by SubQ.
Every model call in Studio is Meta Muse: Spark designs, reviews and answers; Muse Code builds the website.
Each business is also spun off as its own Fetch.ai agent (agents/factory/runtime.py).
"""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from core import subq
from core.meta import MetaError, spark

ROOT = pathlib.Path(__file__).parent.parent.parent
SPEC_DIR = ROOT / "logs" / "studio"
BASE_PORT = 8101

SEEDS = [
    "A math and physics tutoring business for high-school students, online, $40 an hour",
    "A shop selling refurbished laptops (MacBook Air, ThinkPad, Dell XPS) with a 90-day warranty",
    "A yoga studio in Austin with drop-in classes, a monthly unlimited pass and private sessions",
    "A freelance brand designer offering logos, brand kits and pitch decks",
    "A short-term furnished apartment rental business in Lisbon with studio and 2-bedroom units",
    "A walking food-tour guide in Mexico City with small-group and private tours",
    "A licensed plumber doing leak repair, drain cleaning and water heater installs in Chicago",
    "A wedding and event photographer offering half-day, full-day and engagement shoots",
    "A bookkeeping service for small businesses: monthly books, payroll and year-end tax prep",
    "An auto repair garage doing oil changes, brake pads and diagnostics",
]


class Item(BaseModel):
    name: str
    price: float
    unit: str


class Policy(BaseModel):
    key: str
    value: str


class _Reply(BaseModel):
    markdown: str


class Spec(BaseModel):
    name: str
    industry: str
    pitch: str
    catalog: list[Item]
    policies: list[Policy]
    examples: list[str]
    trap: str


DESIGN = ("You design a small business from a founder's one-sentence idea. Return JSON with keys: "
          "name (a real-sounding brand name), industry (one or two words), pitch (one sentence), "
          "catalog (3 to 5 items: name, price as a number in USD, unit like 'per hour' or 'each'), "
          "policies (3 to 4 items: key like 'Hours', 'Location', 'Cancellation', 'Refunds', 'Warranty'; value one short sentence), "
          "examples (3 short things a customer would type, one asking a price, one booking or ordering a specific catalog item, one about a policy), "
          "trap (one plausible service or perk this business does NOT offer, a short noun phrase). "
          "Use the founder's prices exactly when given.")


def _now() -> float:
    return time.time()


def activity(db, business: str, text: str) -> None:
    db.studio_activity.insert_one({"at": _now(), "business": business, "text": text})


def design(prompt: str) -> tuple[dict, str]:
    """Muse Spark turns the founder's sentence into the spec (structured output, schema-checked)."""
    try:
        return spark("studio_design", DESIGN, "FOUNDER: " + prompt, Spec).model_dump(), "muse-spark-1.3"
    except MetaError as e:
        raise RuntimeError(f"Muse Spark could not design it: {e}")


class Issue(BaseModel):
    severity: str
    field: str
    problem: str
    fix: str


class Review(BaseModel):
    ready: bool
    issues: list[Issue]


REVIEW = ("You review a small business's launch spec before customers see it. Flag only real problems: a price that is "
          "missing, zero, or wildly off for the industry and city; a catalog item that contradicts the pitch; a policy that "
          "is vague, unenforceable or contradicts another; a missing policy customers will ask about (refunds, cancellation, "
          "hours, service area); anything that could be illegal or unsafe to promise. severity is high, medium or low. "
          "ready is false only if there is a high-severity issue. At most 5 issues.")


def review(spec: dict) -> dict:
    """Muse Spark checks the spec before launch. Returns {ready, issues, model}."""
    try:
        r = spark("studio_review", REVIEW, json.dumps(spec, ensure_ascii=False), Review)
        return {**r.model_dump(), "model": "muse-spark-1.3", "at": _now()}
    except MetaError as e:
        return {"ready": None, "issues": [], "error": str(e)[:200], "model": "muse-spark-1.3", "at": _now()}


def money(x: float) -> str:
    return f"${x:,.2f}"


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def match_item(spec: dict, text: str):
    """Best catalog item by word overlap, or None."""
    words, best, score = _tokens(text), None, 0
    for it in spec["catalog"]:
        s = len(words & _tokens(it["name"]))
        if s > score:
            best, score = it, s
    return best


def _qty(text: str) -> int:
    m = re.search(r"\b(\d{1,3})\b", text)
    return max(1, int(m.group(1))) if m else 1


def classify(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(book|appointment|schedule|reserve|reservation)\b", t):
        return "booking"
    if re.search(r"\b(order|buy|purchase|checkout)\b", t):
        return "order"
    if re.search(r"\b(quote|estimate)\b", t):
        return "quote"
    if re.search(r"\b(menu|catalog|services|offer|options|list|prices|what do you (sell|do))\b", t):
        return "catalog"
    return "info"


def _facts(spec: dict) -> str:
    return json.dumps({k: spec[k] for k in ("name", "industry", "pitch", "catalog", "policies")}, ensure_ascii=False)


def say(spec: dict, message: str, card: dict | None) -> tuple[str, list[str]]:
    prompt = (f"You are the customer assistant for {spec['name']}. Answer the customer in at most 2 sentences. Use ONLY the "
              "FACTS. If something is not in the FACTS, say you do not offer it or do not know. Never invent prices, "
              "discounts or policies. If a CARD is given, refer to it briefly instead of repeating every number.\n\n"
              f"FACTS: {_facts(spec)}\nCARD: {json.dumps(card) if card else 'none'}\nCUSTOMER: {message}")
    try:
        return spark("studio_say", "Answer as instructed. Put only the reply to the customer in `markdown`.", prompt,
                     _Reply).markdown.strip(), ["muse-spark-1.3"]
    except MetaError:
        return "(no model answered)", []


def card_for(spec: dict, message: str, others: list[dict] | None = None):
    """The card is code, never the model. Returns (card | None, referral business | None)."""
    kind = classify(message)
    if kind == "catalog":
        return {"kind": "catalog", "title": f"{spec['name']}: what we offer", "rows": {}, "items": spec["catalog"]}, None
    if kind == "info":
        return None, None
    item = match_item(spec, message)
    if not item:
        for o in others or []:  # this business does not sell it; a business built in Studio might
            hit = match_item(o["spec"], message)
            if hit:
                return {"kind": "info", "title": f"Referred to {o['spec']['name']}",
                        "rows": {"Why": f"{spec['name']} does not offer this", "They offer": hit["name"],
                                 "Price": f"{money(hit['price'])} {hit['unit']}", "Agent": "@" + o["handle"]},
                        "items": []}, o
        return {"kind": "catalog", "title": "We could not match that. Here is what we offer", "rows": {}, "items": spec["catalog"]}, None
    q = _qty(message) if kind != "booking" else 1
    ref = ("BK-" if kind == "booking" else "OR-" if kind == "order" else "QT-") + uuid.uuid4().hex[:6].upper()
    rows = {"Reference": ref, "Item": item["name"], "Unit price": f"{money(item['price'])} {item['unit']}"}
    if kind != "booking":
        rows["Quantity"] = str(q)
    rows["Total"] = money(item["price"] * q)
    if kind == "booking":
        when = re.search(r"\b(on|at|for|next|this|tomorrow)\b.*$", message, re.I)
        rows["Requested"] = when.group(0).strip() if when else "time to confirm"
        rows["Status"] = "Requested. The owner confirms."
    elif kind == "order":
        rows["Status"] = "Placed. Paying on Fetch testnet."
    else:
        rows["Valid"] = "7 days"
    return {"kind": kind, "title": {"booking": "Booking request", "order": "Order", "quote": "Quote"}[kind] + f": {item['name']}",
            "rows": rows, "items": [], "ref": ref}, None


def answer(spec: dict, message: str, others: list[dict] | None = None) -> dict:
    card, referral = card_for(spec, message, others)
    reply, used = say(spec, message, card)
    return {"reply": reply, "card": card, "used": used, "referral": referral["business_id"] if referral else None}


def _price_ok(expected: float, got: str) -> bool:
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", got)]
    return any(abs(n - expected) < 0.01 for n in nums)


def verify(spec: dict) -> dict:
    qs = [("price", f"How much is {it['name']}?", f"{money(it['price'])} {it['unit']}", it) for it in spec["catalog"][:5]]
    qs += [("policy", f"What is your {p['key'].lower()} policy?" if p["key"].lower() not in ("hours", "location") else
            f"What are your {p['key'].lower()}?" if p["key"].lower() == "hours" else "Where are you located?", p["value"], p)
           for p in spec["policies"][:3]]
    qs.append(("trap", f"Do you offer {spec['trap']}?", f"No: {spec['trap']} is not offered", None))

    def one(q):
        kind, question, expected, ref = q
        got = say(spec, question, None)[0]
        p = None
        if kind == "price":
            ok = _price_ok(ref["price"], got)
        else:
            truth = f"The business's policy is: {expected}" if kind == "policy" else f"The business does NOT offer {spec['trap']}."
            try:
                p = round(subq.yes_probability(f"TRUE FACT: {truth}\nQUESTION: {question}\nAGENT ANSWER: {got}",
                                               "Is the agent's answer consistent with the TRUE FACT?",
                                               "The answer agrees with the true fact (same meaning, wording may differ) and adds no contradicting claim.",
                                               "The answer contradicts the true fact, claims something the fact rules out, or invents a different policy.",
                                               call="subq_studio"), 4)
                ok = p >= 0.5
            except subq.SubQError:
                ok = False
        return {"question": question, "expected": expected, "got": got, "pass": ok, "subq": p, "check": "code" if kind == "price" else "subq"}

    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(one, qs))
    passed = sum(r["pass"] for r in rows)
    return {"score": round(passed / len(rows), 4), "total": len(rows), "passed": passed, "rows": rows, "at": _now()}


# ---- spin-off: each business is its own Fetch.ai agent process ----------------------------------

_procs: dict[str, subprocess.Popen] = {}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24]


def spawn(db, b: dict) -> None:
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    path = SPEC_DIR / f"{b['business_id']}.json"
    path.write_text(json.dumps({**b["spec"], "business_id": b["business_id"], "port": b["port"], "handle": b["handle"],
                                "description": f"{b['spec']['pitch']} Built with LAZARUS Studio."}))
    seed = _seed(b["business_id"])
    log = open(SPEC_DIR / f"{b['business_id']}.log", "w")
    p = subprocess.Popen([sys.executable, "-m", "agents.factory.runtime", str(path)], cwd=ROOT, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, env={**os.environ, "FACTORY_SEED": seed})
    _procs[b["business_id"]] = p
    db.studio.update_one({"business_id": b["business_id"]}, {"$set": {"status": "starting", "pid": p.pid}})

    def watch():
        live = False
        for line in p.stdout:
            log.write(line)
            log.flush()
            m = re.search(r"Connected to Agentverse as (\S+)", line)
            a = re.search(r"Agent address:? *(agent1\w+)", line) or re.search(r"(agent1q\w{40,})", line)
            if a:
                db.studio.update_one({"business_id": b["business_id"]}, {"$set": {"address": a.group(1)}})
            if "Registration on Almanac API successful" in line and not live:
                db.studio.update_one({"business_id": b["business_id"], "status": "starting"}, {"$set": {"status": "registered"}})
                threading.Thread(target=fund, args=(db, b), daemon=True).start()
            if "Agent limit reached" in line:
                db.studio.update_one({"business_id": b["business_id"]}, {"$set": {"status": "registered", "error":
                    "On the Fetch Almanac with its own address and wallet. No Agentverse mailbox: the account is at its 8-agent limit."}})
            if m and not live:
                live = True
                db.studio.update_one({"business_id": b["business_id"]}, {"$set": {"status": "live", "profile_url": m.group(1), "error": None}})
                activity(db, b["spec"]["name"], "is live on Agentverse as its own Fetch.ai agent")
                threading.Thread(target=fund, args=(db, db.studio.find_one({"business_id": b["business_id"]})), daemon=True).start()
        if p.returncode is None or p.returncode < 0:  # we stopped it (API shutdown or restart)
            return
        db.studio.update_one({"business_id": b["business_id"]}, {"$set": {"status": "stopped" if live else "failed",
                                                                         "error": None if live else "agent exited before connecting"}})
    threading.Thread(target=watch, daemon=True).start()


def stop_all() -> None:
    for p in _procs.values():
        p.terminate()


def create(db, prompt: str) -> str:
    bid = "biz-" + uuid.uuid4().hex[:8]
    port = BASE_PORT + db.studio.count_documents({})
    db.studio.insert_one({"business_id": bid, "prompt": prompt, "status": "designing", "created_at": _now(), "port": port})

    def go():
        try:
            spec, model = design(prompt)
            handle = f"{slug(spec['name'])}-{bid[4:8]}"
            db.studio.update_one({"business_id": bid}, {"$set": {"spec": spec, "designed_by": model, "handle": handle,
                                                                "name": spec["name"], "industry": spec["industry"], "pitch": spec["pitch"]}})
            activity(db, spec["name"], f"designed by {model} from: \"{prompt[:80]}\"")
            db.studio.update_one({"business_id": bid}, {"$set": {"status": "reviewing"}})
            rv = review(spec)
            db.studio.update_one({"business_id": bid}, {"$set": {"review": rv}})
            activity(db, spec["name"], f"spec reviewed by Muse Spark: {len(rv['issues'])} issue(s)"
                     + (", ready to launch" if rv.get("ready") else ", needs the owner's attention" if rv.get("ready") is False else ""))
            spawn(db, db.studio.find_one({"business_id": bid}))
            threading.Thread(target=website, args=(db, bid), daemon=True).start()
        except Exception as e:
            db.studio.update_one({"business_id": bid}, {"$set": {"status": "failed", "error": f"{type(e).__name__}: {str(e)[:240]}"}})
    threading.Thread(target=go, daemon=True).start()
    return bid


def resume(db) -> None:
    """After an API restart, bring back every business that was running."""
    for b in db.studio.find({"status": {"$in": ["live", "starting", "stopped", "registered", "failed"]}, "spec": {"$exists": True}}):
        spawn(db, b)
    for b in db.studio.find({"spec": {"$exists": True}}):  # backfill Muse review + website for older businesses
        if not b.get("review"):
            rv = review(b["spec"])
            db.studio.update_one({"business_id": b["business_id"]}, {"$set": {"review": rv}})
            activity(db, b["spec"]["name"], f"spec reviewed by Muse Spark: {len(rv['issues'])} issue(s)")
        if (b.get("site") or {}).get("status") != "ready":
            threading.Thread(target=website, args=(db, b["business_id"]), daemon=True).start()


# ---- real money: live FET price + a real Fetch testnet transfer to the business's own wallet -----

PRICE_URL = "https://api.coingecko.com/api/v3/simple/price?ids=fetch-ai&vs_currencies=usd"
TESTNET_SCALE = 10000  # testnet settles 1/1000 of the mainnet FET amount so the faucet wallet covers every demo
_price = {"usd": None, "at": 0.0}


def fet_usd() -> float | None:
    """Live FET/USD from CoinGecko, cached 60 s. None if unreachable (then no payment is attempted)."""
    import httpx
    if _price["usd"] and _now() - _price["at"] < 60:
        return _price["usd"]
    try:
        _price.update(usd=float(httpx.get(PRICE_URL, timeout=8).json()["fetch-ai"]["usd"]), at=_now())
    except Exception:
        pass
    return _price["usd"]


def _seed(bid: str) -> str:
    return hashlib.sha256((os.environ.get("AGENT_SEED_PHRASE_ORACLE", "") + ":studio:" + bid).encode()).hexdigest()


def agent_wallet(bid: str):
    """The business agent's own Fetch wallet: the same key uagents derives from the agent's seed."""
    from uagents.config import LEDGER_PREFIX
    from uagents_core.identity import derive_key_from_seed
    from cosmpy.aerial.wallet import LocalWallet
    from cosmpy.crypto.keypairs import PrivateKey
    return LocalWallet(PrivateKey(derive_key_from_seed(_seed(bid), LEDGER_PREFIX, 0)), prefix=LEDGER_PREFIX)


def wallet_of(bid: str) -> str:
    return str(agent_wallet(bid).address())


STARTER_FET = 0.3  # testFET the customer agent sends each new business agent so it can buy from others


def fund(db, b: dict) -> None:
    """One real transfer, once per business: oracle agent wallet -> new business agent wallet."""
    from core import anchor
    try:
        from cosmpy.aerial.client import LedgerClient, NetworkConfig
        c, w = LedgerClient(NetworkConfig.fetchai_stable_testnet()), anchor._wallet()
        with _chain_lock:
            if (db.studio.find_one({"business_id": b["business_id"]}) or {}).get("funded_tx"):
                return
            tx = c.send_tokens(wallet_of(b["business_id"]), int(STARTER_FET * 1e18), "atestfet", w,
                               memo=f"LAZARUS-STUDIO starter {b['handle']}").wait_to_complete()
        if tx.response.is_successful():
            db.studio.update_one({"business_id": b["business_id"]}, {"$set": {"funded_tx": tx.tx_hash}})
            activity(db, b["spec"]["name"], f"agent wallet funded with {STARTER_FET} testFET (tx {tx.tx_hash[:10]}…)")
    except Exception as e:
        activity(db, b["spec"]["name"], f"wallet funding failed: {type(e).__name__}")


_chain_lock = threading.Lock()  # one tx at a time from a wallet, so account sequence numbers never collide


_STOP = {"book", "order", "want", "need", "could", "would", "please", "with", "that", "this", "your", "have", "from", "some", "quote", "buy", "purchase", "appointment", "schedule", "reserve", "tomorrow", "next", "week", "today", "also", "like"}


def marketplace(query: str, limit: int = 3) -> list[dict]:
    """Real agents registered on the Fetch.ai Agentverse marketplace."""
    import httpx
    try:
        words = [w for w in re.findall(r"[a-z]+", query.lower()) if len(w) > 3 and w not in _STOP][:4]
        r = httpx.post("https://agentverse.ai/v1/search/agents", timeout=12, json={"search_text": " ".join(words) or query[:60], "limit": limit},
                       headers={"Authorization": "Bearer " + os.environ.get("AGENTVERSE_API_KEY", "")})
        return [{"name": a.get("name"), "address": a["address"], "description": (a.get("description") or "")[:160],
                 "profile_url": f"https://agentverse.ai/agents/details/{a['address']}/profile"}
                for a in r.json().get("agents", [])[:limit] if a.get("address")]
    except Exception:
        return []


def balance(address: str) -> float | None:
    try:
        from cosmpy.aerial.client import LedgerClient, NetworkConfig
        return LedgerClient(NetworkConfig.fetchai_stable_testnet()).query_bank_balance(address, "atestfet") / 1e18
    except Exception:
        return None


def pay(db, b: dict, item: dict, qty: int = 1, buyer: dict | None = None, ref: str | None = None) -> dict:
    """Customer wallet (the LAZARUS demo wallet) pays the business wallet on dorado-1.
    Returns the order with a tx only once the chain confirmed it and the memo reads back."""
    from core import anchor, receipt
    usd = item["price"] * qty
    rate = fet_usd()
    ref = ref or "OR-" + uuid.uuid4().hex[:6].upper()
    order = {"ref": ref, "business_id": b["business_id"], "business": b["spec"]["name"], "item": item["name"], "qty": qty,
             "buyer": buyer["spec"]["name"] if buyer else "LAZARUS Oracle (customer agent)",
             "buyer_id": buyer["business_id"] if buyer else None,
             "usd": usd, "fet_usd": rate, "at": _now(), "status": "failed"}
    if not rate:
        order["error"] = "live FET price unavailable; no payment attempted"
        db.studio_orders.insert_one(dict(order))
        return order
    mainnet_fet = usd / rate
    test_fet = round(mainnet_fet / TESTNET_SCALE, 6)
    to = wallet_of(b["business_id"])
    order.update(mainnet_fet=round(mainnet_fet, 4), testnet_fet=test_fet, to=to)
    try:
        from cosmpy.aerial.client import LedgerClient, NetworkConfig
        c = LedgerClient(NetworkConfig.fetchai_stable_testnet())
        w = agent_wallet(buyer["business_id"]) if buyer else anchor._wallet()
        memo = f"LAZARUS-STUDIO {ref} {b['handle']}"
        with _chain_lock:
            tx = c.send_tokens(to, int(test_fet * 1e18), "atestfet", w, memo=memo).wait_to_complete()
        if not tx.response.is_successful():
            raise RuntimeError("chain rejected the transfer")
        order.update(**{"from": str(w.address())}, tx_hash=tx.tx_hash, memo=memo, explorer=anchor.EXPLORER + tx.tx_hash)
        for _ in range(8):
            got, when = receipt._chain_memo(tx.tx_hash)
            if got:
                break
            time.sleep(2)
        order.update(status="paid" if got == memo else "sent", chain_memo=got, block_time=when)
    except Exception as e:
        order["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    db.studio_orders.insert_one(dict(order))
    activity(db, b["spec"]["name"], f"order {ref} from {order['buyer']} {order['status']}: {item['name']} x{qty}, {money(usd)}"
             + (f" ({test_fet} testFET, tx {order['tx_hash'][:10]}…)" if order.get("tx_hash") else ""))
    return order


def act(db, b: dict, message: str, channel: str = "studio", buyer: dict | None = None) -> dict:
    """One customer message, end to end: card by code, reply by Gemini, payment on chain for orders."""
    others = [o for o in db.studio.find({"spec": {"$exists": True}, "business_id": {"$ne": b["business_id"]}})]
    card, referral = card_for(b["spec"], message, others)
    res = {"reply": None, "card": card, "used": [], "referral": referral["business_id"] if referral else None}
    if res["referral"]:
        o = next(x for x in others if x["business_id"] == res["referral"])
        activity(db, b["spec"]["name"], f"referred a customer to {o['spec']['name']} (@{o['handle']})")
    if card and card["title"].startswith("We could not match"):
        found = marketplace(message)
        if found:
            card = res["card"] = {"kind": "marketplace", "title": "Not offered here. Found on the Fetch.ai marketplace", "items": [],
                                  "rows": {f"{a['name']}": a["address"] for a in found}, "agents": found}
            activity(db, b["spec"]["name"], f"searched Agentverse for \"{message[:40]}\": {len(found)} registered agents")
    if card and card["kind"] == "booking":
        from agents.factory import market
        bitem = match_item(b["spec"], message)
        if bitem:
            ics, when = market.booking_ics(b["spec"], bitem, card["ref"], message)
            market.DELIVERIES.mkdir(parents=True, exist_ok=True)
            (market.DELIVERIES / f"{card['ref']}.ics").write_text(ics)
            db.studio_deliveries.insert_one({"ref": card["ref"], "business_id": b["business_id"], "item": bitem["name"],
                                             "title": f"Calendar invite: {bitem['name']}", "file": f"{card['ref']}.ics", "format": "ics",
                                             "mime": "text/calendar", "sha256": hashlib.sha256(ics.encode()).hexdigest(),
                                             "bytes": len(ics), "status": "delivered", "at": _now()})
            card["rows"].update({"Scheduled": when, "Calendar invite": f"http://127.0.0.1:8030/studio/d/{card['ref']}"})
        activity(db, b["spec"]["name"], f"booking request {card['ref']}: {card['rows']['Item']} ({channel})")
    if card and card["kind"] == "order":
        item = match_item(b["spec"], message)
        o = pay(db, b, item, int(card["rows"].get("Quantity", "1")), buyer=buyer, ref=card["ref"])
        card["ref"] = o["ref"]
        card["rows"]["Reference"] = o["ref"]
        if o["status"] == "paid":
            card["rows"].update({"Status": "PAID on Fetch testnet (confirmed on chain)",
                                 "Live FET price": f"${o['fet_usd']:.4f} (CoinGecko)",
                                 "Mainnet equivalent": f"{o['mainnet_fet']:,.4f} FET",
                                 "Settled": f"{o['testnet_fet']} testFET (1/{TESTNET_SCALE} scale)",
                                 "From agent wallet": o["from"], "To business agent wallet": o["to"], "Tx": o["tx_hash"]})
            card["explorer"] = o["explorer"]
            card["title"] = f"Paid: {item['name']}"
            if b.get("digital"):  # digital product: the seller makes and hands it over now that the money is on chain
                from agents.factory import market
                d = market.deliver(db, b, item, message, o["ref"], buyer=buyer)
                if d.get("status") == "delivered":
                    card["title"] = f"Paid & delivered: {d['title']}"
                    card["rows"].update({"Delivered": f"{d['file']} ({d['bytes']:,} bytes, {d['check']})",
                                         "SHA-256": d["sha256"], "Download": f"http://127.0.0.1:8030/studio/d/{d['ref']}"})
                    if d.get("live"):
                        card["rows"]["Open it live"] = f"http://127.0.0.1:8030/studio/live/{d['ref']}"
                    card["delivery"] = {k: d.get(k) for k in ("ref", "title", "file", "sha256", "bytes", "format", "check", "live")}
                    card["delivery"]["preview"] = (market.DELIVERIES / d["file"]).read_text()[:700]
                    activity(db, b["spec"]["name"], f"delivered \"{d['title']}\" for {o['ref']} (sha256 {d['sha256'][:10]}…)")
                else:
                    card["rows"]["Delivered"] = "NOT yet: " + d.get("error", "failed")
        else:
            card["rows"]["Status"] = "Payment NOT confirmed: " + (o.get("error") or o["status"])
        res["payment"] = {k: o.get(k) for k in ("status", "tx_hash", "explorer", "testnet_fet", "mainnet_fet", "fet_usd", "to", "from")}
    res["reply"], res["used"] = say(b["spec"], message, res["card"])
    db.studio_chats.insert_one({"business_id": b["business_id"], "at": _now(), "channel": channel, "message": message,
                                "reply": res["reply"], "card": card})
    return res


# ---- Muse Code builds each business a small website ----------------------------------------------

SITES = ROOT / "builds" / "sites"
_muse_slots = threading.Semaphore(3)
SITE_PROMPT = """Build a one-page website for this small business as a single file index.html in the workspace root.
Plain HTML and inline CSS only: no JavaScript, no external fonts, scripts, images or links, no forms.
Sections: hero (name + pitch), services table with EVERY catalog item and its exact price and unit, policies,
and a line "Chat with us on Fetch.ai: @{handle}". Professional, high-contrast, readable on a phone.
Use only the facts below; do not invent prices, reviews, addresses, phone numbers or awards.

BUSINESS: {spec}
"""


def website(db, bid: str) -> None:
    from agents.prober.muse_client import MuseError, run_exec
    b = db.studio.find_one({"business_id": bid})
    db.studio.update_one({"business_id": bid}, {"$set": {"site": {"status": "building", "model": "muse-code"}}})
    with _muse_slots:
        try:
            _, ws = run_exec("studio_site", SITE_PROMPT.format(handle=b["handle"], spec=json.dumps(b["spec"], ensure_ascii=False)))
            try:
                html = (ws / "index.html").read_text()
            finally:
                import shutil
                shutil.rmtree(ws, ignore_errors=True)
            out = SITES / bid
            out.mkdir(parents=True, exist_ok=True)
            (out / "index.html").write_text(html)
            missing = [it["name"] for it in b["spec"]["catalog"] if money(it["price"]).replace(".00", "") not in html and money(it["price"]) not in html]
            has_script = bool(re.search(r"<script|javascript:|<iframe|<form", html, re.I))
            site = {"status": "ready", "model": "muse-code", "bytes": len(html), "prices_missing": missing, "has_script": has_script,
                    "check": "every catalog price is on the page" if not missing else f"{len(missing)} price(s) missing", "at": _now()}
            activity(db, b["spec"]["name"], f"website built by Muse Code ({len(html)//1024} KB); " + site["check"])
        except (MuseError, OSError) as e:
            site = {"status": "failed", "model": "muse-code", "error": str(e)[:200], "at": _now()}
        db.studio.update_one({"business_id": bid}, {"$set": {"site": site}})
