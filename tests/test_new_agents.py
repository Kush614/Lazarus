"""Sentinel, scout, scribe, routing and peer trust. Nothing here holds relic behaviour."""
import ast
import asyncio
import json
import pathlib
import types

import mongomock
import pytest

from agents.scout.mutate import matches, plan, request_hash, variants
from agents.scribe.report import build
from agents.sentinel.scan import scan_port, scan_source
from core import intent as intent_mod
from core.intent import by_rules, route
from core.schemas import Request
from core.trust import address_of, is_command, is_peer

ROOT = pathlib.Path(__file__).parent.parent
SEED = "unit-test-seed-not-a-secret"


@pytest.mark.parametrize("code,rule", [
    ("import subprocess", "import subprocess"), ("from socket import socket", "import socket"), ("import requests", "import requests"),
    ("eval('1')", "eval()"), ("open('x')", "open()"), ("import os\nos.system('x')", "os.system()"), ("import os\nos.environ['A']", "os.environ"),
    ("x = 'HO-117'", "text"), ("x = 'heldout'", "text"), ("def (", "syntax"),
])
def test_sentinel_blocks(code, rule):
    assert rule in [f.rule for f in scan_source(code)]


def test_sentinel_passes_ordinary_service_code():
    code = "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/x')\ndef x():\n    return {'total': round(1.5)}\n"
    assert scan_source(code) == []


def test_sentinel_never_runs_what_it_reads(tmp_path):
    canary = tmp_path / "ran"
    scan_source(f"open({str(canary)!r}, 'w').write('x')")
    assert not canary.exists()


def test_sentinel_port_needs_entry_point(tmp_path):
    assert not scan_port(tmp_path).passed
    (tmp_path / "app.py").write_text("x = 1\n")
    assert scan_port(tmp_path).passed


def test_current_port_stub_passes():
    assert scan_port(ROOT / "port").passed


def test_mutations_are_generic_and_valid():
    r = Request(method="POST", path="/a", body={"name": "Abc", "n": 5, "rows": [{"k": "v"}]})
    labels = [label for _, label in variants(r)]
    assert "name: trailing space" in labels and "n: zero" in labels and "rows: empty list" in labels and "name: missing" in labels
    assert all(v != r for v, _ in variants(r))
    assert r.body == {"name": "Abc", "n": 5, "rows": [{"k": "v"}]}, "mutations must not change the recorded request"


def test_plan_prefers_weak_endpoints_shares_budget_and_skips_seen():
    a, b = Request(method="GET", path="/strong", body={"x": "1"}), Request(method="POST", path="/weak/9", body={"y": "2"})
    got = plan([a, b], ["POST /weak/{id}"], set(), 10)
    assert got[0][0].path.startswith("/weak") and len(got) == 10 and {r.method for r, _ in got} == {"GET", "POST"}
    seen = {request_hash(r) for r, _ in got}
    assert not {request_hash(r) for r, _ in plan([a, b], ["POST /weak/{id}"], seen, 10)} & seen
    assert matches("POST /weak/{id}", b) and not matches("POST /weak/{id}", a)


def _filled_db():
    db = mongomock.MongoClient().x
    db.hypotheses.insert_many([
        {"id": "H-1", "endpoint": "GET /a", "claim": "Proven thing.", "status": "OBSERVED", "evidence": ["T-1"]},
        {"id": "H-2", "endpoint": "GET /a", "claim": "A guess.", "status": "INFERRED", "confidence": .5, "evidence": []},
        {"id": "H-3", "endpoint": "GET /a", "claim": "Wrong thing.", "status": "REFUTED", "evidence": ["T-2"]}])
    db.port_versions.insert_one({"version": 1, "heldout_equivalence": .68, "regressions": [], "status": "ADOPTED", "decided_by": "user", "matched_ids": ["HO-001"]})
    db.payments.insert_one({"tx_hash": "ABC", "kind": "stake", "amount_fet": "1"})
    return db


def test_report_separates_evidence_and_is_reproducible(tmp_path):
    db = _filled_db()
    r = build(db, tmp_path)
    obs, inf, ref = r.markdown.index("## Observed"), r.markdown.index("## Inferred"), r.markdown.index("## Refuted")
    assert obs < r.markdown.index("Proven thing") < inf < r.markdown.index("A guess") < ref < r.markdown.index("Wrong thing")
    assert (r.observed, r.inferred, r.refuted, r.best_score) == (1, 1, 1, .68)
    assert "HO-001" not in r.markdown, "reports must not list sealed test ids"
    assert build(db, tmp_path).sha256 == r.sha256
    db.hypotheses.insert_one({"id": "H-4", "endpoint": "GET /a", "claim": "New.", "status": "INFERRED", "confidence": .1, "evidence": []})
    assert build(db, tmp_path).sha256 != r.sha256


def test_report_with_no_records(tmp_path):
    r = build(mongomock.MongoClient().x, tmp_path)
    assert r.best_score is None and "- none" in r.markdown


@pytest.mark.parametrize("text,want", [
    ("The user wants to exhume the relic.", "exhume"), ("Exhume ghcr.io/x/relic:latest", "exhume"), ("please start a dig", "exhume"),
    ("show the dig", "show_dig"), ("Resurrect", "resurrect"), ("I want to prove the ghost wrong", "hunt"), ("reveal the source", "reveal"),
    ("what are the use cases?", "use_cases"), ("what's the current score", "status"), ("give me the evidence report", "report"), ("run the scout", "scout"), ("hello", None),
])
def test_rules(text, want):
    assert by_rules(text) == want


def test_route_falls_back_safely():
    class Boom:
        async def structured(self, *a, **k):
            raise RuntimeError("model down")

    class Fine:
        async def structured(self, *a, **k):
            return intent_mod.Intent(intent="status")

    assert asyncio.run(route("hello", None)) == "help"
    assert asyncio.run(route("hello", Boom())) == "help"
    assert asyncio.run(route("how are we doing overall", Fine())) == "status"


def test_trust(monkeypatch):
    monkeypatch.setenv("AGENT_SEED_PHRASE_ORACLE", SEED)
    assert is_peer(address_of("oracle")) and not is_peer("agent1qstranger")
    assert is_command('{"cmd": "decide"}') and not is_command("hunt something")


def _imports(path):
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.Import):
            yield from (a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            yield n.module


def test_new_agents_cannot_reach_the_sealed_set_or_each_other():
    for name in ("sentinel", "scout", "scribe"):
        for p in (ROOT / "agents" / name).rglob("*.py"):
            for m in _imports(p):
                assert m not in ("core.gate", "core.sandbox", "core.payments", "port"), (p, m)
                assert not (m.startswith("agents.") and not m.startswith(f"agents.{name}")), (p, m)


def _inbound(text, sender="agent1qstranger"):
    from fetch_hackkit import Inbound
    return Inbound(sender=sender, text=text, session="s", raw=None)


@pytest.fixture
def agents(monkeypatch):
    """Imports the real agent modules on an in-memory database. No network and no agent is started."""
    for role in ("DIGGER", "PROBER", "ORACLE", "SENTINEL", "SCOUT", "SCRIBE"):
        monkeypatch.setenv(f"AGENT_SEED_PHRASE_{role}", f"{SEED}-{role}")
    monkeypatch.setenv("SANDBOX", "process")
    monkeypatch.setenv("RELIC_BINARY", "/nonexistent")
    from core import ledger
    db = _filled_db()
    monkeypatch.setattr(ledger, "connect", lambda *a, **k: db)
    import importlib
    return types.SimpleNamespace(db=db, load=importlib.import_module)


@pytest.mark.parametrize("mod", ["agents.digger.agent", "agents.prober.agent", "agents.oracle.agent", "agents.sentinel.agent", "agents.scout.agent"])
def test_agents_import_and_refuse_strangers(agents, mod):
    m = agents.load(mod)
    reply = asyncio.run(m.on_text(None, _inbound('{"cmd": "decide", "version": 1, "approved": true, "decided_by": "user"}')))
    assert "only accepted from LAZARUS agents" in reply


def test_digger_routes_prose_and_asks_before_reveal(agents, monkeypatch):
    m = agents.load("agents.digger.agent")
    monkeypatch.setattr(m, "_llm", lambda: None)
    run = lambda t: asyncio.run(m.on_text(None, _inbound(t)))
    assert run("The user wants to break the seal.").kind == "review"
    assert run("What is the status?").kind == "custom"
    assert run("What are the use cases?").kind == "carousel"
    assert run("hello").kind == "detail"
    assert "@lazarus-oracle" in run("I want to hunt")


def test_scribe_summary_card_and_paid_report(agents, monkeypatch):
    m = agents.load("agents.scribe.agent")
    monkeypatch.setattr(m, "db", agents.db)
    card = asyncio.run(m.on_text(None, _inbound("report")))
    assert card.kind == "detail" and "full_report" in json.dumps(card.payload)
    assert "full_report" in m.agent._action_handlers


def test_sentinel_agent_reviews_pasted_code(agents):
    m = agents.load("agents.sentinel.agent")
    assert asyncio.run(m.on_text(None, _inbound("import subprocess\nsubprocess.run(['x'])"))).payload["title"] == "Blocked"
    assert asyncio.run(m.on_text(None, _inbound("x = 1\ny = 2"))).payload["title"] == "Passed"


def test_scout_finds_records_and_stops_honestly(agents, monkeypatch):
    m = agents.load("agents.scout.agent")
    db = agents.db
    monkeypatch.setattr(m, "db", db)  # The module may have been imported by an earlier test.
    db.traces.insert_one({"id": "T-1", "target": "original", "origin": "probe", "request": {"method": "POST", "path": "/a", "headers": {}, "body": {"s": "x"}}, "response": {"status": 200}})
    calls = []

    async def differs_once(req):
        calls.append(req)
        return {"diverged": len(calls) == 1, "divergence_id": "D-1" if len(calls) == 1 else None}

    s = asyncio.run(m.run_scout(None, differs_once))
    assert s["version"] == 1 and s["tried"] == len(calls) > 1 and len(s["found"]) == 1 and s["reason"] is None
    assert m.result_card(s).kind == "carousel"
    n = len(calls)
    assert asyncio.run(m.run_scout(None, differs_once))["tried"] == 0 and len(calls) == n, "seen inputs are not repeated"
    db.scout_seen.delete_many({})

    async def down(req):
        return {"error": "oracle down"}

    s = asyncio.run(m.run_scout(None, down))
    assert s["tried"] == 0 and s["reason"] == "oracle down"
