"""Digital-product businesses that sell to customers and trade with each other.

Every sale of a digital product is delivered: after the payment is confirmed on chain, the seller
(Muse Spark) produces the purchased product for that buyer, it is saved, hashed (SHA-256) and handed
over as a download. Muse Spark also maps the supply chain (who needs what from whom); a market round
makes buyer agents pay seller agents wallet-to-wallet and the sellers deliver.
"""
import hashlib
import json
import pathlib
import random
import threading
import time

from pydantic import BaseModel

from agents.factory import studio
from core.meta import MetaError, spark

DELIVERIES = studio.ROOT / "builds" / "deliveries"

DIGITAL_SEEDS = [
    "PDF-to-quiz maker: turns any study notes into a 20-question quiz with answers, $3 per quiz",
    "Resume roaster for software engineers: scored critique plus a rewritten resume, $9",
    "Logo and brand kit maker: SVG logo, color palette and font pairing, $25",
    "Landing page copywriter: hero, features, FAQ and CTA copy for a startup, $19",
    "Contract red-flag checker for freelancers: risky clauses with severity and safer wording, $12",
    "Wedding and event speech writer from five answers, three tones, $15",
    "Daily crypto and stock market brief on your tickers, $4 per brief",
    "SEO keyword research pack: 50 keywords with intent and difficulty, $14",
    "Social media post pack: 30 posts for LinkedIn and X for a month, $18",
    "Cold email sequence writer: 4-email B2B outreach sequence, $16",
    "Pitch deck outline builder: 12-slide investor deck outline with talking points, $29",
    "Shopify product description writer: SEO product descriptions, $2 per product",
    "Python code reviewer: bugs, security issues and a fixed version of a snippet, $10",
    "English-Spanish translation service for marketing copy, $0.05 per word",
    "Podcast show-notes writer: summary, timestamps and quotes, $8 per episode",
    "Interview prep pack: 40 role-specific questions with model answers, $11",
    "Personal meal plan generator: 7-day plan with grocery list, $6",
    "Travel itinerary planner: day-by-day plan with budget, $9",
    "Study flashcard maker: 100 spaced-repetition flashcards from a topic, $5",
    "Privacy policy and terms generator for apps and websites, $20",
]


class Edge(BaseModel):
    buyer: str
    seller: str
    item: str
    why: str


class Edges(BaseModel):
    edges: list[Edge]


class Product(BaseModel):
    title: str
    content: str


# What a buyer actually receives, by product type: a real file in a usable format, checked by code.
FORMATS = [
    (("logo", "brand", "icon", "mark"), "svg", "image/svg+xml",
     "ONE complete standalone SVG document (<svg xmlns=...> ... </svg>), 512x512 viewBox, the actual logo artwork with "
     "shapes and the brand name as <text>. No external fonts or images. Nothing outside the <svg> element."),
    (("landing", "website", "web page", "page pack", "headline", "hero", "features section", "policy", "terms", "privacy", "quiz"),
     "html", "text/html",
     "ONE complete, self-contained HTML5 page (<!doctype html> ... </html>) with inline CSS, ready to publish as-is. "
     "For a quiz, make it interactive with inline JavaScript: questions, choices, a Submit button and a score. "
     "For a policy, the full legal text with headings. No external links, scripts, fonts or images."),
    (("email", "outreach", "sequence"), "csv", "text/csv",
     "A mail-merge CSV with header: send_day,subject,body. One row per email, body as plain text in double quotes."),
    (("keyword", "seo"), "csv", "text/csv",
     "A CSV with header: keyword,intent,difficulty,monthly_searches_estimate,suggested_page. At least the promised number of rows."),
    (("flashcard", "cards"), "csv", "text/csv",
     "An Anki-importable CSV with header: front,back,tags. At least the promised number of cards."),
    (("post", "social", "hooks"), "csv", "text/csv",
     "A Buffer-style schedule CSV with header: date,platform,text. One row per post, dates from 2026-11-09 onward."),
    (("product description", "description"), "csv", "text/csv",
     "A Shopify import CSV with header: Handle,Title,Body (HTML),Tags. One row per product."),
    (("meal", "grocery", "diet"), "csv", "text/csv",
     "A CSV with header: day,meal,dish,ingredients,grocery_item,quantity. A full week."),
    (("code", "python", "review", "security"), "py", "text/x-python",
     "A complete, runnable Python 3 file: the reviewed and FIXED code, with the review findings as comments at the top. "
     "It must compile. Do not import third-party packages."),
    (("itinerary", "travel", "trip"), "ics", "text/calendar",
     "An iCalendar file (BEGIN:VCALENDAR ... END:VCALENDAR, VERSION:2.0, PRODID) with one VEVENT per day, starting 2026-11-20, "
     "each with DTSTART/DTEND (YYYYMMDDTHHMMSS), UID, SUMMARY and a DESCRIPTION of the day's plan and budget."),
]
DEFAULT = ("md", "text/markdown", "The complete deliverable in markdown, ready to use, with no placeholders.")


def format_for(item: str, pitch: str) -> tuple[str, str, str]:
    t = item.lower()
    for keys, ext, mime, how in FORMATS:
        if any(k in t for k in keys):
            return ext, mime, how
    t = (item + " " + pitch).lower()
    for keys, ext, mime, how in FORMATS:
        if any(k in t for k in keys):
            return ext, mime, how
    return DEFAULT


def check(ext: str, content: str) -> str | None:
    """Code, not the model, decides whether the file is a real one. Returns a problem or None."""
    import csv
    import io
    import xml.etree.ElementTree as ET
    c = content.strip()
    try:
        if ext == "svg":
            root = ET.fromstring(c)
            if not root.tag.endswith("svg") or len(list(root.iter())) < 3:
                return "not a real SVG drawing"
        elif ext == "html":
            if "<html" not in c.lower() or "</html>" not in c.lower() or len(c) < 800:
                return "not a complete HTML page"
        elif ext == "csv":
            rows = list(csv.reader(io.StringIO(c)))
            if len(rows) < 4 or len(rows[0]) < 2 or any(len(r) != len(rows[0]) for r in rows[1:] if r):
                return f"CSV is ragged or too short ({len(rows)} rows)"
        elif ext == "py":
            compile(c, "delivery.py", "exec")
        elif ext == "ics":
            if not (c.startswith("BEGIN:VCALENDAR") and c.endswith("END:VCALENDAR") and "BEGIN:VEVENT" in c):
                return "not a valid calendar file"
    except (ET.ParseError, SyntaxError, ValueError, csv.Error) as e:
        return f"{type(e).__name__}: {str(e)[:120]}"
    return None


def _strip_fence(c: str) -> str:
    c = c.strip()
    if c.startswith("```"):
        c = c.split("\n", 1)[1] if "\n" in c else ""
        c = c.rsplit("```", 1)[0]
    return c.strip()


def seed(db) -> list[str]:
    have = {b["prompt"] for b in db.studio.find({}, {"prompt": 1})}
    ids = []
    for p in DIGITAL_SEEDS:
        if p not in have:
            bid = studio.create(db, p)
            db.studio.update_one({"business_id": bid}, {"$set": {"digital": True}})
            ids.append(bid)
    return ids


def deliver(db, seller: dict, item: dict, request: str, ref: str, buyer: dict | None = None) -> dict:
    """The seller makes the purchased product as a real file. Called only after the payment is confirmed on chain."""
    ext, mime, how = format_for(item["name"], seller["spec"]["pitch"])
    who = (f"The buyer is the business {buyer['spec']['name']}: {buyer['spec']['pitch']} Make it FOR that business (its name, its customers)."
           if buyer else "The buyer is an individual customer.")
    instructions = (f"You are {seller['spec']['name']} ({seller['spec']['pitch']}). The customer has PAID for '{item['name']}'. "
                    f"Deliver the actual product, not a plan or a description of it. FORMAT: {how} Put the whole file, and nothing "
                    "else, in `content` (no code fences). No placeholders like [Your Name] or 'lorem ipsum'; no invented facts "
                    "about real people or companies. `title` is a short name for the file.")
    problem, p = None, None
    for attempt in range(2):
        try:
            p = spark("studio_deliver", instructions + (f" The previous file was rejected: {problem}. Fix it." if problem else ""),
                      f"{who}\nCustomer request: {request}", Product)
        except MetaError as e:
            return {"status": "failed", "error": str(e)[:200]}
        p.content = _strip_fence(p.content)
        if p.content.count("\\n") > p.content.count("\n"):  # the model escaped its newlines
            p.content = p.content.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
        problem = check(ext, p.content)
        if not problem:
            break
    if problem:
        return {"status": "failed", "error": f"the {ext} file did not pass the check: {problem}"}
    DELIVERIES.mkdir(parents=True, exist_ok=True)
    path = DELIVERIES / f"{ref}.{ext}"
    path.write_text(p.content)
    sha = hashlib.sha256(p.content.encode()).hexdigest()
    d = {"ref": ref, "business_id": seller["business_id"], "item": item["name"], "title": p.title, "file": path.name,
         "format": ext, "mime": mime, "sha256": sha, "bytes": len(p.content.encode()), "status": "delivered",
         "check": f"valid {ext.upper()} (checked by code)", "model": "muse-spark-1.3", "at": time.time(),
         "buyer_id": buyer["business_id"] if buyer else None, "live": ext in ("html", "svg")}
    db.studio_deliveries.insert_one(dict(d))
    return d


def booking_ics(spec: dict, item: dict, ref: str, when_text: str) -> tuple[str, str]:
    """A real calendar invite for a booked service. The time is parsed from the request, else tomorrow 10:00."""
    import datetime as dt
    import re as _re
    now = dt.datetime.now()
    day = now + dt.timedelta(days=1)
    t = when_text.lower()
    for i, name in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]):
        if name in t:
            day = now + dt.timedelta(days=(i - now.weekday()) % 7 or 7)
    hour, minute = 10, 0
    m = _re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t)
    if m:
        hour = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0)
        minute = int(m.group(2) or 0)
    start = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    end = start + dt.timedelta(hours=1)
    f = "%Y%m%dT%H%M%S"
    ics = "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//LAZARUS Studio//EN", "BEGIN:VEVENT",
                         f"UID:{ref}@lazarus-studio", f"DTSTAMP:{now.strftime(f)}", f"DTSTART:{start.strftime(f)}", f"DTEND:{end.strftime(f)}",
                         f"SUMMARY:{item['name']} with {spec['name']}",
                         f"DESCRIPTION:Booking {ref}. {item['name']} ({studio.money(item['price'])} {item['unit']}). Booked via LAZARUS Studio on Fetch.ai.",
                         "END:VEVENT", "END:VCALENDAR"])
    return ics, start.strftime("%a %d %b %Y, %H:%M")


def map_supply_chain(db) -> list[dict]:
    bs = list(db.studio.find({"digital": True, "spec": {"$exists": True}}))
    listing = [{"id": b["business_id"], "name": b["spec"]["name"], "pitch": b["spec"]["pitch"],
                "sells": [i["name"] for i in b["spec"]["catalog"]]} for b in bs]
    try:
        out = spark("studio_supply_chain",
                    "These are small digital businesses. For each one, pick 1 or 2 products it would genuinely BUY from another "
                    "business in the list to run or grow itself (e.g. a landing-page writer buys a logo kit and SEO keywords). "
                    "Use exact ids for buyer and seller and an exact item name from the seller's 'sells'. why: one short sentence. "
                    "Never pair a business with itself.", json.dumps(listing), Edges)
    except MetaError:
        return []
    ids = {b["business_id"]: b for b in bs}
    edges = []
    for e in out.edges:
        s = ids.get(e.seller)
        if e.buyer in ids and s and e.buyer != e.seller and any(i["name"] == e.item for i in s["spec"]["catalog"]):
            edges.append({"buyer": e.buyer, "seller": e.seller, "item": e.item, "why": e.why,
                          "buyer_name": ids[e.buyer]["spec"]["name"], "seller_name": s["spec"]["name"]})
    db.studio_edges.delete_many({})
    if edges:
        db.studio_edges.insert_many([dict(x) for x in edges])
    studio.activity(db, "Market", f"Muse Spark mapped the supply chain: {len(edges)} buy/sell links between {len(bs)} businesses")
    return edges


_running = {"on": False, "rounds": 0}


def trade(db, e: dict) -> dict:
    buyer, seller = db.studio.find_one({"business_id": e["buyer"]}), db.studio.find_one({"business_id": e["seller"]})
    res = studio.act(db, seller, f"order 1 {e['item']}", channel=f"b2b from {buyer['spec']['name']}", buyer=buyer)
    c = res["card"] or {}
    db.studio_trades.insert_one({"at": time.time(), "buyer": buyer["spec"]["name"], "seller": seller["spec"]["name"], "item": e["item"],
                                 "why": e["why"], "status": (res.get("payment") or {}).get("status"), "tx_hash": (res.get("payment") or {}).get("tx_hash"),
                                 "explorer": c.get("explorer"), "delivery": c.get("delivery"), "ref": c.get("ref")})
    return res


def run(db, rounds: int = 3, per_round: int = 3) -> None:
    """Market rounds in the background: each round, a few buyers purchase from sellers along the mapped edges."""
    if _running["on"]:
        return

    def go():
        _running.update(on=True, rounds=0)
        try:
            edges = list(db.studio_edges.find()) or map_supply_chain(db)
            for r in range(rounds):
                for e in random.sample(edges, min(per_round, len(edges))):
                    trade(db, e)
                _running["rounds"] = r + 1
        finally:
            _running["on"] = False
    threading.Thread(target=go, daemon=True).start()


def status() -> dict:
    return dict(_running)
