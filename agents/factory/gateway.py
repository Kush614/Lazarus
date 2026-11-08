"""LAZARUS Studio inside ASI:One: the whole flow through one Agentverse agent (@lazarus-digger), with buttons.
Every button runs the same code as the console, so payments, deliveries and checks are the real ones."""
import asyncio
import re

from fetch_hackkit import cards

from agents.factory import market, studio

TRIGGERS = ("studio", "market", "businesses", "start a business", "create a business", "trades", "lazarus flow", "marketplace")


LAZARUS_WORDS = re.compile(r"^\s*(exhume|resurrect|reveal|status|receipt|ledger|show dig|challenge|hunt|scout|use cases|help)\b|"
                           r"\b(seal|relic|reveal|exhume|resurrect|legacy|binary|port|dig|hypothes\w*|divergen\w*|status|use cases?|hunt|challenge|scout|receipt|proof)\b", re.I)


def wants(text: str) -> bool:
    """Studio handles everything from people except the original LAZARUS commands, so chat never hangs."""
    t = text.lower().strip()
    return any(t.startswith(k) or t == k for k in TRIGGERS) or not LAZARUS_WORDS.search(t)


def home(db):
    n = db.studio.count_documents({})
    live = db.studio.count_documents({"status": {"$in": ["live", "registered"]}})
    paid = db.studio_orders.count_documents({"status": "paid"})
    trades = db.studio_trades.count_documents({"status": "paid"})
    files = db.studio_deliveries.count_documents({"status": "delivered"})
    rows = {
        "1. Describe": "A founder types one sentence: \"start a business: …\"",
        "2. Design": "Fetch.ai + Meta Muse Spark turn it into a catalog, prices and policies",
        "3. Pre-launch check": "Fetch.ai + Meta Muse Spark flag risky or missing policies; Fetch.ai + Meta Muse Code build the website",
        "4. Go live": "It becomes its own Fetch.ai agent with its own wallet",
        "5. Verify": "LAZARUS asks questions with known answers; SubQ grades them -> trust score",
        "6. Sell": "Customers (or other agents) pay in FET on the Fetch testnet, confirmed on chain",
        "7. Deliver": "The seller hands over a real file: SVG logo, web page, CSV, calendar, code",
        "8. Trade": "Businesses buy from each other along a supply chain Fetch.ai + Meta Muse Spark mapped",
        "Right now": f"{n} businesses · {live} on Fetch · {paid} paid orders · {trades} agent-to-agent trades · {files} files delivered",
    }
    return cards.detail("LAZARUS Studio: businesses that sell, deliver and trade", rows=rows, ctas=[
        cards.cta("Browse", "gw_browse", primary=True, page=0), cards.cta("Market", "gw_market"),
        cards.cta("Trades", "gw_trades"), cards.cta("New business", "gw_start_help")],
        narration="This is the whole LAZARUS Studio flow, live. Tap a button.")


def browse(db, page: int = 0):
    bs = list(db.studio.find({"spec": {"$exists": True}}).sort([("digital", -1), ("created_at", 1)]))
    chunk = bs[page * 8:(page + 1) * 8]
    tiles = [cards.item(b["business_id"], b["spec"]["name"], action="gw_biz", cta_label="Open",
                        subtitle=f"{b['spec']['industry']} · from {studio.money(min(i['price'] for i in b['spec']['catalog']))}",
                        secondary_text="Digital products" if b.get("digital") else "Services",
                        badges=[cards.badge(f"trust {b['verification']['score']:.0%}", "success")] if b.get("verification") else None)
             for b in chunk]
    if (page + 1) * 8 < len(bs):
        tiles.append(cards.item("next", "More businesses", action="gw_browse", cta_label="Next page",
                                subtitle=f"{len(bs) - (page + 1) * 8} more", page=page + 1))
    return cards.carousel(f"Businesses ({page * 8 + 1}-{page * 8 + len(chunk)} of {len(bs)})", tiles,
                          subtitle="Each one is its own Fetch.ai agent with its own wallet. Tap Open.", narration="Pick a business.")


def business(db, bid: str):
    b = db.studio.find_one({"business_id": bid})
    if not b:
        return home(db)
    v = b.get("verification")
    rows = {"What they do": b["spec"]["pitch"], "Agent": "@" + b["handle"], "Wallet": studio.wallet_of(bid)}
    if v:
        rows["Trust"] = f"{v['passed']}/{v['total']} answers verified (SubQ)"
    for i, it in enumerate(b["spec"]["catalog"][:3]):
        rows[f"{i + 1}. {it['name']}"] = f"{studio.money(it['price'])} {it['unit']}"
    ctas = [cards.cta(f"Buy {i + 1} · {studio.money(it['price']).replace('.00', '')}", "gw_buy", primary=(i == 0), id=bid, i=i)
            for i, it in enumerate(b["spec"]["catalog"][:2])]
    ctas += [cards.cta("Verify", "gw_verify", id=bid), cards.cta("Back", "gw_browse", page=0)]
    return cards.detail(b["spec"]["name"], rows=rows, ctas=ctas, narration=b["spec"]["pitch"])


def quiz_items(c: str) -> list[tuple[str, list[str], str]]:
    """(question, options, correct answer) from a delivered quiz page: a JS data array, or form fieldsets plus an answer map."""
    import html as _html
    S = r"""([`'"])((?:\\.|(?!\1).)*?)\1"""
    txt = lambda x: re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()
    out = []
    # 1. JS array: {q:`...`, opts:[`a`,`b`], a:1}
    for m in re.finditer(r"(?:q|question|text|prompt)['\"]?\s*:\s*" + S + r"\s*,\s*(?:opts|options|choices|answers|o)['\"]?\s*:\s*\[(.*?)\]\s*,\s*(?:a|answer|correct|correctIndex)['\"]?\s*:\s*(\d+|" + S + ")", c, re.S):
        opts = [o[1] for o in re.findall(S, m.group(3), re.S)]
        a = m.group(4)
        ans = opts[int(a)] if a.isdigit() and int(a) < len(opts) else (m.group(6) or "")
        out.append((m.group(2).strip(), opts, ans))
    if out:
        return out
    # 2. Form: <legend>question</legend> ... <label>option</label>, answers in a {q1:'B'} map
    key = dict(re.findall(r"q(\d+)\s*:\s*['\"]([A-Z])['\"]", c))
    for n, block in enumerate(re.split(r"(?i)<legend[^>]*>", c)[1:], 1):
        q, _, rest = block.partition("</legend>")
        q = re.sub(r"^\d+\s*", "", txt(q))
        opts = [txt(o) for o in re.findall(r"(?is)<label[^>]*>(.*?)</label>", rest.split("<legend")[0].split("</fieldset>")[0])]
        letter = key.get(str(n), "")
        ans = next((o for o in opts if o.startswith(letter + ")")), letter) if letter else ""
        if q:
            out.append((q, opts, ans))
    if out:
        return out
    # 3. Anything that reads as a question
    return [(txt(x), [], "") for x in re.findall(r"(?is)<(?:h[2-4]|legend|p|div|label)[^>]*>((?:(?!</?(?:div|p|h\d|legend)).){12,300}?\?)\s*<", c)]


def inline(d: dict) -> tuple[dict, str | None]:
    """The delivered product itself, shown inside the card: rows of real content and, for a logo, the image."""
    import base64
    import csv
    import html as _html
    import io
    f = market.DELIVERIES / d["file"]
    if not f.exists():
        return {}, None
    c = f.read_text().replace("\\n", "\n").replace('\\"', '"')
    fmt = d.get("format")
    if fmt == "svg":
        return {"Logo": "shown above (SVG, embedded)"}, "data:image/svg+xml;base64," + base64.b64encode(c.encode()).decode()
    if fmt == "csv":
        rows = list(csv.reader(io.StringIO(c)))
        head = rows[0] if rows else []
        out = {}
        for n, r in enumerate(rows[1:9], 1):
            out[f"{n}. {r[0][:40]}"] = " · ".join(x[:60] for x in r[1:3])
        out["Rows in file"] = f"{len(rows) - 1} ({', '.join(head[:4])})"
        return out, None
    if fmt == "html":
        quiz = quiz_items(c)
        if len(quiz) >= 3:
            return {f"{n}. {q}": "  ·  ".join(opts) + (f"   ✓ {ans}" if ans else "")
                    for n, (q, opts, ans) in enumerate(quiz, 1)}, None
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", c)
        text = re.sub(r"(?i)<br\s*/?>|</(p|h[1-6]|li|div|label|button)>", "\n", text)
        lines = [_html.unescape(re.sub(r"<[^>]+>", " ", x)).strip() for x in text.split("\n")]
        skip = re.compile(r"^(submit|retake|answer key|\d+ of \d+ answered|home)\b", re.I)
        lines = [re.sub(r"\s+", " ", x) for x in lines if len(x.strip()) > 2 and not skip.match(x.strip())][:12]
        return {f"{n}.": x[:160] for n, x in enumerate(lines, 1)}, None
    if fmt == "ics":
        ev = re.findall(r"DTSTART[^:]*:(\d{8})T?(\d{4})?.*?SUMMARY:([^\r\n]+)", c, re.S)
        return {f"{x[0][:4]}-{x[0][4:6]}-{x[0][6:]}" + (f" {x[1][:2]}:{x[1][2:]}" if x[1] else ""): x[2][:120] for x in ev[:8]}, None
    lines = [x for x in c.splitlines() if x.strip()][:10]
    return {f"{n}.": x[:160] for n, x in enumerate(lines, 1)}, None


async def buy(db, bid: str, i: int):
    b = db.studio.find_one({"business_id": bid})
    it = b["spec"]["catalog"][i]
    res = await asyncio.to_thread(studio.act, db, b, f"order 1 {it['name']}", "asi:one via @lazarus-digger")
    c = res["card"] or {}
    r = c.get("rows") or {}
    rows = {k: r[k] for k in ("Status", "Total", "Settled", "Tx", "SHA-256") if k in r}
    if c.get("explorer"):
        rows["Explorer"] = c["explorer"]
    out = [cards.detail(c.get("title", "Order"), rows=rows or r, ctas=[cards.cta("Buy again", "gw_buy", id=bid, i=i),
                        cards.cta("Business", "gw_biz", id=bid), cards.cta("Home", "gw_home")], narration=res["reply"])]
    d = db.studio_deliveries.find_one({"ref": c.get("ref")}) if c.get("ref") else None
    if d:
        content, image = inline(d)
        if content:
            out.append(cards.detail(f"Your product: {d.get('title', d['file'])}", rows=content, hero_image=image,
                                    ctas=[cards.cta("Home", "gw_home")],
                                    narration=f"Here it is: {d['file']}, {d.get('check', 'delivered')}."))
    return out


async def verify(db, bid: str):
    b = db.studio.find_one({"business_id": bid})
    v = await asyncio.to_thread(studio.verify, b["spec"])
    db.studio.update_one({"business_id": bid}, {"$set": {"verification": v}})
    rows = {r["question"][:60]: ("PASS" if r["pass"] else "FAIL") + (f" · SubQ {r['subq']:.0%}" if r.get("subq") is not None else " · code check")
            for r in v["rows"]}
    rows["Score"] = f"{v['passed']}/{v['total']}"
    return cards.detail(f"Verified: {b['spec']['name']}", rows=rows, ctas=[cards.cta("Back", "gw_biz", id=bid)],
                        narration="Questions whose answers LAZARUS already knows; prices checked by code, policies by SubQ.")


def market_round(db):
    market.run(db, rounds=1, per_round=2)
    return cards.detail("Market round started", rows={
        "What happens": "2 businesses buy from suppliers Fetch.ai + Meta Muse Spark mapped for them",
        "Payment": "buyer agent wallet -> seller agent wallet on the Fetch testnet",
        "Delivery": "the seller makes the real file and hands it over",
        "Time": "about a minute; then tap Recent trades"},
        ctas=[cards.cta("Trades", "gw_trades", primary=True), cards.cta("Home", "gw_home")],
        narration="Market round running.")


def trades(db):
    ts = list(db.studio_trades.find().sort("at", -1).limit(8))
    rows = {f"{t['buyer']} <- {t['seller']}": f"{t['item'][:40]} · {t.get('status')} · " +
            ((t.get("delivery") or {}).get("file") or "no file") + (f" · tx {t['tx_hash'][:10]}…" if t.get("tx_hash") else "")
            for t in ts}
    st = market.status()
    return cards.detail("Recent agent-to-agent trades", rows=rows or {"Trades": "none yet"},
                        ctas=[cards.cta("Refresh", "gw_trades", primary=True), cards.cta("Market", "gw_market"),
                              cards.cta("Home", "gw_home")],
                        narration="A round is still running." if st["on"] else "Latest trades, newest first.")


def start(db, text: str):
    desc = text.split(":", 1)[1].strip() if ":" in text else ""
    if not desc:  # "I want to register my video editing business", "start a bakery"
        m = re.search(r"(?:register|start|create|open|launch|build)\s+(?:my |a |an )?(.{4,})", text, re.I)
        desc = m.group(1).strip() if m else ""
    if len(desc) < 8:
        return cards.detail("Start a business", rows={"How": "Type: start a business: <one sentence, with prices if you like>",
                                                       "Example": "start a business: dog-walking in Austin, $25 per 30-minute walk"},
                            ctas=[cards.cta("Home", "gw_home")], narration="Describe it in one sentence.")
    bid = studio.create(db, desc[:400])
    return cards.detail("Designing your business", rows={"Idea": desc[:200], "Next": "Fetch.ai + Meta Muse Spark design it, check it, then it goes live as a Fetch agent (about a minute)"},
                        ctas=[cards.cta("Open", "gw_biz", primary=True, id=bid), cards.cta("Home", "gw_home")],
                        narration="Your business is being built.")


async def handle_text(db, text: str):
    t = text.lower().strip()
    if t.startswith(("start a business", "create a business")) or re.search(r"\b(register|start|create|open|launch|build)\b.*\b(business|shop|store|studio|agency|service|company)\b", t):
        return start(db, text)
    if t.startswith("trades"):
        return trades(db)
    if t.startswith("market"):
        return trades(db) if "trades" in t else home(db)
    if t.startswith("businesses"):
        return browse(db)
    return home(db)
