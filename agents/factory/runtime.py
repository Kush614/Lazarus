"""A Studio business as its own Fetch.ai agent. One generic runtime driven by the spec the founder's
sentence produced; it runs no generated code. Customers reach it on Agentverse / ASI:One and get the
same cards (catalog, quote, booking, paid order) as the Studio UI. The seed comes from env, never argv.

usage: FACTORY_SEED=... python -m agents.factory.runtime <spec.json>
"""
import asyncio
import json
import re
import os
import pathlib
import sys

from dotenv import dotenv_values, load_dotenv

_ENV = pathlib.Path(__file__).parent.parent.parent / ".env"
load_dotenv(_ENV)
# The console API blanks this key for itself; a spun-off business must connect its own mailbox.
os.environ["AGENTVERSE_API_KEY"] = dotenv_values(_ENV).get("AGENTVERSE_API_KEY") or ""

from fetch_hackkit import HackAgent, cards  # noqa: E402

from agents.factory import studio  # noqa: E402
from core import ledger  # noqa: E402

SPEC = json.loads(pathlib.Path(sys.argv[1]).read_text())
db = ledger.connect()

agent = HackAgent(SPEC["name"], seed=os.environ["FACTORY_SEED"], port=int(SPEC["port"]), handle=SPEC["handle"],
                  description=SPEC["description"])


def _items():
    return SPEC["catalog"]


def _menu(narration: str = ""):
    tiles = [cards.item(str(i), it["name"], action="studio_choose", cta_label="Choose",
                        subtitle=f"{studio.money(it['price'])} {it['unit']}", secondary_text=SPEC["industry"])
             for i, it in enumerate(_items())]
    return cards.carousel(f"{SPEC['name']}: menu", tiles, subtitle="Tap an item to order, book or get a quote",
                          narration=narration or "Here is what we offer.")


def _item_card(i: int):
    it = _items()[i]
    return cards.detail(it["name"], rows={"Price": f"{studio.money(it['price'])} {it['unit']}", "Business": SPEC["name"],
                                          "Payment": "FET on Fetch testnet, agent wallet to agent wallet"},
                        ctas=[cards.cta("Order & pay", "studio_order", primary=True, id=str(i), qty=1),
                              cards.cta("Book", "studio_book", id=str(i)), cards.cta("Get quote", "studio_quote", id=str(i)),
                              cards.cta("Back to menu", "studio_menu")],
                        narration=f"{it['name']}: {studio.money(it['price'])} {it['unit']}.")


def _ctas(c: dict) -> list:
    i = next((n for n, it in enumerate(_items()) if it["name"] == c["rows"].get("Item")), None)
    if c["kind"] == "quote" and i is not None:
        return [cards.cta("Accept & pay", "studio_order", primary=True, id=str(i), qty=int(c["rows"].get("Quantity", "1"))),
                cards.cta("Book instead", "studio_book", id=str(i)), cards.cta("Menu", "studio_menu")]
    if c["kind"] == "booking" and i is not None:
        return [cards.cta("Pay now", "studio_order", primary=True, id=str(i), qty=1), cards.cta("Menu", "studio_menu")]
    if c["kind"] == "order" and i is not None:
        return [cards.cta("Order again", "studio_order", primary=True, id=str(i), qty=1), cards.cta("Menu", "studio_menu")]
    return [cards.cta("Menu", "studio_menu")]


async def _run(text: str):
    b = db.studio.find_one({"business_id": SPEC["business_id"]})
    res = await asyncio.to_thread(studio.act, db, b, text, "asi:one")  # payments wait ~15 s for the chain
    c = res["card"]
    if not c:
        return cards.detail(SPEC["name"], rows={"Answer": res["reply"]}, ctas=[cards.cta("See menu", "studio_menu", primary=True)],
                            narration=res["reply"])
    if c["kind"] == "catalog":
        return _menu(res["reply"])
    rows = dict(c["rows"])
    if c.get("explorer"):
        rows["Explorer"] = c["explorer"]
    for a in c.get("agents") or []:
        rows[a["name"]] = a["profile_url"]
    return cards.detail(c["title"], rows=rows, ctas=_ctas(c), narration=res["reply"])


def _pick(sel: dict) -> int | None:
    """Item index from a direct tap ({"id": "2"}) or a planner-routed tap (prose that contains the id)."""
    raw = sel.get("id")
    if raw is None and sel.get("prose"):
        m = re.search(r"\bid\W{0,4}(\d+)", sel["prose"])
        raw = m.group(1) if m else None
    try:
        i = int(raw)
        return i if 0 <= i < len(_items()) else None
    except (TypeError, ValueError):
        return None


@agent.on_action("studio_menu")
async def a_menu(ctx, inbound, sel):
    return _menu()


@agent.on_action("studio_policies")
async def a_policies(ctx, inbound, sel):
    return cards.detail(f"{SPEC['name']}: policies", rows={p["key"]: p["value"] for p in SPEC["policies"]},
                        ctas=[cards.cta("See menu", "studio_menu", primary=True)], narration="Our policies.")


@agent.on_action("studio_choose")
async def a_choose(ctx, inbound, sel):
    i = _pick(sel)
    return _item_card(i) if i is not None else _menu()


@agent.on_action("studio_order")
async def a_order(ctx, inbound, sel):
    i = _pick(sel)
    if i is None:
        return _menu()
    qty = max(1, min(int(sel.get("qty") or 1), 99))
    return await _run(f"order {qty} {_items()[i]['name']}")


@agent.on_action("studio_book")
async def a_book(ctx, inbound, sel):
    i = _pick(sel)
    return await _run(f"book {_items()[i]['name']}") if i is not None else _menu()


@agent.on_action("studio_quote")
async def a_quote(ctx, inbound, sel):
    i = _pick(sel)
    return await _run(f"quote for 1 {_items()[i]['name']}") if i is not None else _menu()


@agent.on_text
async def on_text(ctx, msg):
    text = cards.strip_mention(msg.text).strip()
    if not text or text.lower() in ("help", "hi", "hello", "start"):
        return cards.detail(SPEC["name"], rows={"What we do": SPEC["pitch"], "Industry": SPEC["industry"],
                                                "Try": " · ".join(SPEC.get("examples", [])[:3])},
                            ctas=[cards.cta("See menu", "studio_menu", primary=True), cards.cta("Policies", "studio_policies")],
                            narration=f"Welcome to {SPEC['name']}. Built with LAZARUS Studio.")
    return await _run(text)


if __name__ == "__main__":
    agent.run()
