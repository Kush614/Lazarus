"""Chat with LAZARUS Studio businesses from the terminal.

usage:  uv run python scripts/studio_chat.py            interactive (through the LAZARUS API)
        uv run python scripts/studio_chat.py --fetch    interactive over Fetch.ai: a real uAgent sends Agent Chat
                                                        Protocol messages to each business's agent address
        uv run python scripts/studio_chat.py 1 "order 2 pepperoni pizza"   one message to business #1

commands:  /list            all businesses          /use N        talk to business N
           /buy N <msg>     current business buys from business N (agent wallet -> agent wallet)
           /verify          LAZARUS checks the business tells the truth
           /info            catalog, policies, wallet          /quit
           /links           who buys from whom (mapped by Muse Spark)
           /market [N]      run a market round: N businesses buy from each other, paid on chain, delivered
           /trades          recent business-to-business trades
           /subq            SubQ usage per API key (both keys alternate) and recent judgements
           /tap N           (--fetch) press button N on the last card, exactly like tapping it in ASI:One
"""
import json
import sys
import urllib.request

API = "http://127.0.0.1:8030"
B, D, G, R, Y, C, X = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[0m"


def call(method: str, path: str, body=None, timeout=180):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": f"{e.code} {e.read().decode()[:200]}"}
    except OSError as e:
        sys.exit(f"{R}LAZARUS API not reachable on {API}: {e}{X}")


def businesses():
    return call("GET", "/studio/businesses")


def show_list(bs):
    for i, b in enumerate(bs, 1):
        st = b["status"]
        col = G if st == "live" else C if st == "registered" else Y
        trust = f" trust {b['trust_score']:.0%}" if b.get("trust_score") is not None else ""
        print(f" {B}{i:>2}{X}  {b['name']:<28} {D}{(b.get('industry') or ''):<20}{X} {col}{'on Fetch' if st == 'registered' else st}{X}{trust}")


def show_card(c):
    if not c:
        return
    paid = c["rows"].get("Status", "").startswith("PAID") and c.get("explorer")
    print(f"  {G if paid else C}┌─ {B}{c['title']}{X}")
    for k, v in c["rows"].items():
        col = G if k == "Status" and paid else R if k == "Status" and "NOT" in str(v) else ""
        print(f"  │ {D}{k:<26}{X} {col}{v}{X}")
    for it in c.get("items") or []:
        print(f"  │ {it['name']:<34} {B}${it['price']:,.2f}{X} {D}{it['unit']}{X}")
    for a in c.get("agents") or []:
        print(f"  │ {B}{a['name']}{X}  {D}{a['profile_url']}{X}")
    if c.get("explorer"):
        print(f"  │ {D}explorer{X} {c['explorer']}")
    print(f"  └─")


def show_reply(r):
    if r.get("error"):
        print(f"{R}{r['error']}{X}")
        return
    print(f"{B}agent:{X} {r['reply']}  {D}[{', '.join(r.get('used') or ['no model'])}]{X}")
    show_card(r.get("card"))


def info(b):
    d = call("GET", f"/studio/businesses/{b['business_id']}")
    s = d.get("spec") or {}
    print(f"{B}{d['name']}{X} — {d.get('pitch')}\n  {D}@{d.get('handle')}  agent {d.get('address')}{X}")
    print(f"  wallet {d.get('wallet')}  {G}{(d.get('wallet_balance_testfet') or 0):.4f} testFET{X}")
    for it in s.get("catalog", []):
        print(f"  • {it['name']:<34} ${it['price']:,.2f} {it['unit']}")
    for p in s.get("policies", []):
        print(f"  {D}{p['key']}:{X} {p['value']}")
    if s.get("examples"):
        print(f"  {D}try:{X} " + "  |  ".join(s["examples"]))


FETCH = None
BUTTONS: list = []


def fetch_setup(bs):
    """Starts the CLI customer uAgent. Mailbox-less businesses are reached at their own Fetch endpoint."""
    global FETCH
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from dotenv import load_dotenv
    load_dotenv(__import__("pathlib").Path(__file__).parent.parent / ".env")
    from core import ledger
    from scripts.studio_fetch import FetchClient
    db = ledger.connect()
    local = {d["address"]: f"http://127.0.0.1:{d['port']}/submit" for d in db.studio.find({"address": {"$exists": True}, "status": {"$ne": "live"}})}  # live ones: real mailbox
    addr = {d["business_id"]: d["address"] for d in db.studio.find({"address": {"$exists": True}})}
    for b in bs:
        b["address"] = addr.get(b["business_id"])
    FETCH = FetchClient(local)
    print(f"{D}Fetch mode: you are uAgent {FETCH.address} speaking the Agent Chat Protocol{X}")


def fetch_chat(b, text):
    from scripts.studio_fetch import render
    if not b.get("address"):
        print(f"{R}{b['name']} has no agent address yet{X}")
        return
    print(f"{D}  → ChatMessage to {b['address'][:22]}… ({'Agentverse mailbox' if b['status'] == 'live' else 'Fetch endpoint'}){X}")
    seen = False
    BUTTONS.clear()
    for kind, content in FETCH.ask(b["address"], text):
        if kind == "ack":
            print(f"{D}  ✓ ChatAcknowledgement from the agent{X}")
            continue
        seen = True
        lines, buttons = render(content)
        BUTTONS.extend(buttons)
        if content.get("type") == "text":
            print(f"{B}agent:{X} {lines[0]}")
        else:
            paid = any("PAID" in l for l in lines)
            print(f"  {G if paid else C}┌─ {B}{lines[0]}{X}")
            for l in lines[1:]:
                print(f"  │{G if paid and 'PAID' in l else ''}{l}{X}")
            print("  └─")
    if not seen:
        print(f"{R}  no reply within 90 s{X}")
    elif BUTTONS:
        print(f"{D}  tap a button: /tap N{X}")


def main():
    use_fetch = "--fetch" in sys.argv
    if use_fetch:
        sys.argv.remove("--fetch")
    bs = businesses()
    if use_fetch:
        fetch_setup(bs)
    if len(sys.argv) >= 3:
        b = bs[int(sys.argv[1]) - 1]
        print(f"{D}→ {b['name']}{X}")
        if use_fetch:
            fetch_chat(b, " ".join(sys.argv[2:]))
        else:
            show_reply(call("POST", f"/studio/businesses/{b['business_id']}/chat", {"message": " ".join(sys.argv[2:])}))
        return
    m = call("GET", "/studio/market")
    print(f"{B}LAZARUS Studio{X}  {D}FET ${m['fet_usd']:.4f} live ({m['source']}) · customer agent wallet "
          f"{m['customer_balance_testfet']:.2f} testFET · settles 1/{m['testnet_scale']}{X}\n")
    show_list(bs)
    cur = bs[0]
    print(f"\n{D}/use N · /buy N <msg> · /links · /market 3 · /trades · /verify · /info · /list · /quit{X}\n")
    while True:
        try:
            line = input(f"{C}you → {cur['name']}{X} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line in ("/quit", "/q", "exit"):
            return
        if line == "/list":
            show_list(bs)
        elif line.startswith("/use"):
            try:
                cur = bs[int(line.split()[1]) - 1]
                info(cur)
            except (IndexError, ValueError):
                print("usage: /use N")
        elif line.startswith("/tap") and use_fetch:
            try:
                btn = BUTTONS[int(line.split()[1]) - 1]
            except (IndexError, ValueError):
                print("usage: /tap N (a button number from the last card)")
                continue
            print(f"{D}  tapping [{btn['label']}] → {json.dumps(btn['selection'])}{X}")
            fetch_chat(cur, json.dumps(btn["selection"]))
        elif line == "/links":
            for e in call("GET", "/studio/market/edges"):
                print(f"  {B}{e['buyer_name']}{X} buys {C}{e['item']}{X} from {B}{e['seller_name']}{X}  {D}{e['why']}{X}")
        elif line.startswith("/market"):
            n = int(line.split()[1]) if len(line.split()) > 1 and line.split()[1].isdigit() else 3
            print(f"{D}market round: {n} buyer agents pay seller agents on Fetch, sellers deliver (Muse Spark)…{X}")
            before = {t.get("ref") for t in call("GET", "/studio/trades")}
            call("POST", "/studio/market/run", {"rounds": 1, "per_round": n})
            import time as _t
            while call("GET", "/studio/market/status").get("on"):
                _t.sleep(3)
            for t in call("GET", "/studio/trades"):
                if t.get("ref") in before:
                    continue
                d = t.get("delivery") or {}
                ok = t.get("status") == "paid"
                print(f"  {G if ok else R}{'PAID' if ok else t.get('status')}{X} {B}{t['buyer']}{X} bought {C}{t['item']}{X} from {B}{t['seller']}{X}")
                print(f"       {D}why:{X} {t['why']}")
                if t.get("explorer"):
                    print(f"       {D}tx:{X} {t['explorer']}")
                if d:
                    print(f"       {D}delivered:{X} {d.get('title')} · {d.get('bytes')} bytes · sha256 {d.get('sha256', '')[:16]}… · {API}/studio/d/{d.get('ref') or t.get('ref')}")
        elif line == "/subq":
            d = call("GET", "/subq/console?limit=8")
            print(f"{B}SubQ Snap{X} {d['model_in_use']} · keys {', '.join(d['keys_configured'])} · mode {d['key_mode']}")
            print(f"  {D}models:{X} {', '.join(d['models_available'])}")
            for k in d["keys"]:
                print(f"  {B}{k['key']:<8}{X} calls {k['calls']:<4} ok {k['ok']:<4} refused {k['refused']:<3} failovers {k['failovers']:<3} "
                      f"tokens in {k['input_tokens']:<6} avg {k['avg_seconds']}s")
            print(f"  {D}where:{X} " + ", ".join(f"{a} {n}" for a, n in d["by_call_site"].items()))
            for r in d["recent"]:
                p = r.get("yes_probability")
                print(f"  {r['key']:<8} {r['status']} {('%.0f%%' % (p * 100)) if p is not None else '  - '} {D}{(r.get('question') or '')[:70]}{X}")
        elif line == "/trades":
            for t in call("GET", "/studio/trades")[:15]:
                print(f"  {t.get('status')} {t['buyer']} ← {t['item']} ← {t['seller']}  {D}{(t.get('tx_hash') or '')[:12]}{X}")
        elif line == "/info":
            info(cur)
        elif line.startswith("/buy"):
            parts = line.split(maxsplit=2)
            try:
                seller = bs[int(parts[1]) - 1]
            except (IndexError, ValueError):
                print("usage: /buy N <message>")
                continue
            msg = parts[2] if len(parts) > 2 else "order 1 " + call("GET", f"/studio/businesses/{seller['business_id']}")["spec"]["catalog"][0]["name"]
            print(f"{D}{cur['name']}'s agent wallet buys from {seller['name']}: \"{msg}\" (waiting for the chain…){X}")
            show_reply(call("POST", f"/studio/businesses/{cur['business_id']}/buy", {"seller_id": seller["business_id"], "message": msg}))
        elif line == "/verify":
            print(f"{D}asking {cur['name']} questions whose answers LAZARUS already knows…{X}")
            v = call("POST", f"/studio/businesses/{cur['business_id']}/verify")
            for r in v.get("rows", []):
                mark = f"{G}PASS{X}" if r["pass"] else f"{R}FAIL{X}"
                sq = f" SubQ {r['subq']:.0%}" if r.get("subq") is not None else " code check"
                print(f"  {mark} {r['question']}\n       {D}expected:{X} {r['expected']}\n       {D}said:{X} {r['got'][:140]}{D}{sq}{X}")
            print(f"  {B}trust {v.get('passed')}/{v.get('total')}{X}")
        else:
            if "order" in line.lower() or "buy" in line.lower():
                print(f"{D}(paying on Fetch testnet, ~15 s){X}")
            if use_fetch:
                fetch_chat(cur, line)
            else:
                show_reply(call("POST", f"/studio/businesses/{cur['business_id']}/chat", {"message": line}))


if __name__ == "__main__":
    main()
