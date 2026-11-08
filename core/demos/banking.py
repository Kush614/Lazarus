"""Banking demo: rebuild a live, third-party IBAN validation service from the outside.

The target is openiban.com, a real public service we did not write and cannot read. The run:
  1. SEAL   generate a held-out set of IBANs, ask the live service, hash inputs + answers.
            The hash is fixed before any code is written.
  2. DIG    probe the live service with a separate set; Muse Spark turns traces into claims,
            and only claims that cite real trace ids count as OBSERVED (checked by code).
  3. PORT   Gemini writes validate(iban) from the observed claims and traces only.
  4. SCAN   the sentinel parses the code; anything unsafe is refused before it runs.
  5. GATE   the port runs in a separate, isolated Python; answers are compared with the live
            service's on the held-out set. SubQ gives a second opinion on each difference.
  6. IMPROVE fresh probes (never the held-out set) find differences; Gemini patches; gate again.
Every step is stored on the run document so the UI can show it as it happens.
"""
import hashlib
import json
import random
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid

import httpx
from pydantic import BaseModel

from agents.sentinel.scan import scan_source
from core import gemini, subq
from core.meta import MetaError, spark

TARGET = "https://openiban.com/validate/"
COUNTRIES = {  # BBAN builders: (length of IBAN, function(rng) -> BBAN)
    "DE": lambda r: _digits(r, 18),
    "NL": lambda r: _letters(r, 4) + _digits(r, 10),
    "GB": lambda r: _letters(r, 4) + _digits(r, 14),
    "AT": lambda r: _digits(r, 16),
    "CH": lambda r: _digits(r, 17),
}


def _digits(r, n):
    return "".join(r.choice("0123456789") for _ in range(n))


def _letters(r, n):
    return "".join(r.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(n))


def check_digits(country: str, bban: str) -> str:
    s = bban + country + "00"
    n = int("".join(str(int(c, 36)) for c in s))
    return f"{98 - n % 97:02d}"


def make_iban(r, country=None) -> str:
    c = country or r.choice(list(COUNTRIES))
    bban = COUNTRIES[c](r)
    return c + check_digits(c, bban) + bban


def variants(r, n: int) -> list[str]:
    """Valid IBANs plus the ways people really mistype them."""
    out = []
    for i in range(n):
        iban = make_iban(r)
        kind = i % 8
        if kind == 1:
            iban = iban.lower()
        elif kind == 2:
            iban = " ".join(iban[j:j + 4] for j in range(0, len(iban), 4))
        elif kind == 3:
            d = (int(iban[2]) + 1) % 10
            iban = iban[:2] + str(d) + iban[3:]
        elif kind == 4:
            iban = iban[:-1]
        elif kind == 5:
            iban = iban[:6] + iban[7] + iban[6] + iban[8:]
        elif kind == 6:
            iban = r.choice(["XX", "ZZ", "QA"]) + iban[2:]
        out.append(iban)
    return out


def ask_live(iban: str, get=None) -> dict | None:
    url = TARGET + urllib.parse.quote(iban, safe="")
    try:
        r = (get or (lambda u: httpx.get(u, timeout=20)))(url)
        return {"status": r.status_code, "body": r.json()}
    except (httpx.HTTPError, ValueError):
        return None


class Code(BaseModel):
    code: str


def write_code(prompt: str) -> tuple[str, str]:
    """Gemini leads; Muse Spark writes the code if Gemini is rate-limited or down."""
    try:
        return gemini.ask("bank_port", prompt, chain=gemini.LEAD, thinking="high")
    except gemini.GeminiError:
        return spark("bank_port", "Write the requested Python. Put only the code in `code`.", prompt, Code).code, "muse-spark-1.3"


class Claim(BaseModel):
    claim: str
    evidence: list[str]
    confidence: float


class Claims(BaseModel):
    claims: list[Claim]


PORT_PROMPT = """You are rebuilding a legacy IBAN validation web service whose source is lost. You may only use the
observed behaviour below. Write one Python function:

def validate(iban: str) -> dict

It must return exactly the JSON body the service returns for GET /validate/<iban>, including every key, the
same key order and the same strings. Use only the Python standard library. No I/O, no network, no imports
other than standard library modules for strings and maths.

OBSERVED CLAIMS (each backed by real traces):
{claims}

REAL TRACES (input -> exact response body):
{traces}
{extra}
Return only the Python code, no explanation, no code fences."""


def _code(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip() + "\n"


RUNNER = """import json, sys
ns = {}
exec(open(sys.argv[1]).read(), ns)
out = []
for iban in json.loads(sys.stdin.read()):
    try:
        out.append({"ok": True, "body": ns["validate"](iban)})
    except Exception as e:
        out.append({"ok": False, "error": type(e).__name__})
print(json.dumps(out))
"""


def run_port(code: str, ibans: list[str]) -> list[dict]:
    """Runs generated code in a separate isolated interpreter (-I: no site, no env, no cwd on path)."""
    with tempfile.TemporaryDirectory(prefix="lazarus-bank-") as td:
        src, runner = f"{td}/port.py", f"{td}/runner.py"
        open(src, "w").write(code)
        open(runner, "w").write(RUNNER)
        p = subprocess.run([sys.executable, "-I", runner, src], input=json.dumps(ibans), capture_output=True,
                           text=True, timeout=30, cwd=td, env={})
        if p.returncode:
            return [{"ok": False, "error": "crashed"} for _ in ibans]
        return json.loads(p.stdout)


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


class Run:
    def __init__(self, db, run_id: str, held_n=40, probe_n=24, seed=None):
        self.db, self.id = db, run_id
        self.held_n, self.probe_n = held_n, probe_n
        self.seed = seed if seed is not None else int(time.time())

    def step(self, name: str, status: str, **data):
        self.db.demo_runs.update_one({"run_id": self.id}, {"$push": {"steps": {"name": name, "status": status, "at": time.time(), **data}},
                                                          "$set": {"current": name}})

    def finish(self, **data):
        self.db.demo_runs.update_one({"run_id": self.id}, {"$set": {"status": "done", "finished_at": time.time(), **data}})

    def fail(self, why: str):
        self.db.demo_runs.update_one({"run_id": self.id}, {"$set": {"status": "failed", "error": why[:400]}})

    def go(self):
        try:
            self._go()
        except Exception as e:  # any failure is shown on the run, never swallowed
            self.fail(f"{type(e).__name__}: {e}")

    def _ask_many(self, ibans):
        out = []
        for iban in ibans:
            out.append({"input": iban, "answer": ask_live(iban)})
            time.sleep(0.15)  # be polite to a public service
        return out

    def _gate(self, code, held):
        got = run_port(code, [h["input"] for h in held])
        rows, matched = [], 0
        for h, g in zip(held, got):
            same = h["answer"] is not None and g["ok"] and canon(g["body"]) == canon(h["answer"]["body"])
            matched += same
            rows.append({"input": h["input"], "match": same, "live": h["answer"]["body"] if h["answer"] else None,
                         "port": g.get("body") if g["ok"] else {"error": g.get("error")}})
        return matched, rows

    def _go(self):
        r_held, r_probe = random.Random(self.seed), random.Random(self.seed + 1)
        # 1. SEAL
        held = self._ask_many(variants(r_held, self.held_n))
        if any(h["answer"] is None for h in held):
            raise RuntimeError("the live service did not answer every held-out input")
        sealed = hashlib.sha256("\n".join(canon(h) for h in held).encode()).hexdigest()
        self.step("seal", "done", held_out=len(held), sha256=sealed, target=TARGET,
                  note="Inputs and live answers hashed before any code exists. The builder never sees them.")

        # 2. DIG
        probes = self._ask_many(variants(r_probe, self.probe_n))
        traces = [{"id": f"BT-{i + 1:03d}", "input": p["input"], "body": p["answer"]["body"]} for i, p in enumerate(probes) if p["answer"]]
        ids = {t["id"] for t in traces}
        try:
            got = spark("bank_claims", "These are real request/response traces from a legacy IBAN validation service. List the "
                        "behaviour rules you can see, each citing the trace ids that show it. Do not state rules no trace shows.",
                        json.dumps(traces)[:30000], Claims)
            claims = [{"claim": c.claim, "evidence": [e for e in c.evidence if e in ids], "confidence": c.confidence} for c in got.claims]
            claim_model = "muse-spark-1.3"
        except MetaError:
            data, claim_model = gemini.ask_json("bank_claims", "List behaviour rules shown by these IBAN service traces as "
                                                '{"claims":[{"claim":..., "evidence":[trace ids], "confidence":0-1}]}.\n' + json.dumps(traces), chain=gemini.FAST)
            claims = [{"claim": c["claim"], "evidence": [e for e in c.get("evidence", []) if e in ids], "confidence": c.get("confidence", 0.5)} for c in data["claims"]]
        for c in claims:
            c["status"] = "OBSERVED" if c["evidence"] else "INFERRED"
        self.step("dig", "done", probes=len(traces), traces=traces, claims=claims, model=claim_model)

        # 3-5. PORT, SCAN, GATE
        observed = [c for c in claims if c["status"] == "OBSERVED"]
        version, best, extra = 0, None, ""
        for attempt in range(2):
            version += 1
            prompt = PORT_PROMPT.format(claims=json.dumps(observed, indent=1), traces=json.dumps(traces)[:20000], extra=extra)
            text, model = write_code(prompt)
            code = _code(text)
            findings = [f.model_dump() for f in scan_source(code, "port.py")]
            self.step("port", "done", version=version, model=model, code=code, lines=code.count("\n"))
            if findings:
                self.step("scan", "blocked", version=version, findings=findings[:10])
                extra = "\nYour last code was refused by the safety scanner for: " + json.dumps(findings[:5]) + "\nAvoid those constructs.\n"
                continue
            self.step("scan", "passed", version=version)
            matched, rows = self._gate(code, held)
            score = matched / len(held)
            parent = best["score"] if best else None
            regressions = sorted({r["input"] for r in best["rows"] if r["match"]} - {r["input"] for r in rows if r["match"]}) if best else []
            adopted = (parent is None or score > parent) and not regressions
            judged = []
            for row in [x for x in rows if not x["match"]][:4]:
                try:
                    judged.append({"input": row["input"], "subq_genuine": round(subq.genuine_divergence(row["live"], row["port"], {"iban": row["input"]}), 3)})
                except subq.SubQError as e:
                    judged.append({"input": row["input"], "subq_error": str(e)})
            self.step("gate", "adopted" if adopted else "blocked", version=version, matched=matched, total=len(held), score=score,
                      regressions=len(regressions), parent=parent, subq=judged,
                      mismatches=len([x for x in rows if not x["match"]]))  # held-out rows themselves never leave the gate
            if adopted:
                best = {"version": version, "score": score, "rows": rows, "code": code, "model": model}
            if score == 1.0:
                break
            # 6. IMPROVE from fresh probes only, never from the held-out set.
            r_more = random.Random(self.seed + 100 + attempt)
            fresh = self._ask_many(variants(r_more, 16))
            got = run_port(best["code"] if best else code, [f["input"] for f in fresh])
            diffs = [{"input": f["input"], "live": f["answer"]["body"], "port": g.get("body")} for f, g in zip(fresh, got)
                     if f["answer"] and not (g["ok"] and canon(g["body"]) == canon(f["answer"]["body"]))]
            self.step("improve", "done", fresh_probes=len(fresh), differences=len(diffs), examples=diffs[:3])
            if not diffs:
                break
            traces += [{"id": f"BT-{len(traces) + i + 1:03d}", "input": d["input"], "body": d["live"]} for i, d in enumerate(diffs)]
            extra = "\nYour previous version answered these fresh inputs differently from the live service:\n" + json.dumps(diffs[:8])[:8000] + "\n"
        self.finish(best_version=best["version"] if best else None, best_score=best["score"] if best else 0.0,
                    best_model=best["model"] if best else None, sealed_sha256=sealed)


def start(db, held_n=40, probe_n=24) -> str:
    run_id = "bank-" + uuid.uuid4().hex[:8]
    db.demo_runs.insert_one({"run_id": run_id, "module": "banking", "status": "running", "steps": [], "started_at": time.time()})
    threading.Thread(target=Run(db, run_id, held_n, probe_n).go, daemon=True).start()
    return run_id
