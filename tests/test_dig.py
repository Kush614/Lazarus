import asyncio

import mongomock
import pytest
from pydantic import ValidationError

from agents.digger.dig import Verdict, apply_verdict, dig, stats, store_initial
from agents.prober.muse_client import SealBreach, audit
from core import ledger, meta
from core.schemas import Hypothesis, Probe, Request, Response, Trace


def db():
    d = mongomock.MongoClient().x
    ledger.ensure_indexes(d)
    return d


def draft(claim="c", status="OBSERVED"):
    return Hypothesis(id="x", endpoint="GET /x", claim=claim, status=status, confidence=.9, evidence=["forged"], source="probe", created_version=9)


def trace(i="T-0001"):
    return Trace(id=i, request=Request(method="GET", path="/x"), response=Response(status=200, body={}), origin="probe", target="original")


def test_schema_refuses_dishonest_claims():
    with pytest.raises(ValidationError):
        Hypothesis(id="H", endpoint="e", claim="c", status="OBSERVED", source="log", created_version=1)
    with pytest.raises(ValidationError):
        Hypothesis(id="H", endpoint="e", claim="c", status="INFERRED", source="log", created_version=1)


def test_model_cannot_start_a_claim_as_observed():
    d = db()
    h = store_initial(d, [draft()], 1)[0]
    assert h.status == "INFERRED" and h.evidence == [] and h.id == "H-0001"


def test_observed_evidence_is_the_real_trace():
    d = db()
    h = store_initial(d, [draft()], 1)[0]
    h2 = apply_verdict(d, h, Verdict(status="OBSERVED"), trace("T-0042"))
    assert h2.evidence == ["T-0042"]


def test_refuted_claim_stays_and_correction_is_inferred():
    d = db()
    h = store_initial(d, [draft("wrong")], 1)[0]
    apply_verdict(d, h, Verdict(status="REFUTED", corrected_claim="right"), trace())
    docs = {x["claim"]: x for x in d.hypotheses.find()}
    assert docs["wrong"]["status"] == "REFUTED" and docs["right"]["status"] == "INFERRED"


def run_dig(d, verdict, trace_result=trace(), budget=40, n_probes=1):
    async def design(h):
        return [Probe(id="p", hypothesis_id=h.id, request=Request(method="GET", path="/x"), rationale="r") for _ in range(n_probes)]
    async def run(r):
        return trace_result
    async def interp(h, p, t):
        return verdict
    return asyncio.run(dig(d, design, run, interp, max_probes=budget))


def test_loop_flips_and_counts():
    d = db()
    store_initial(d, [draft("a"), draft("b")], 1)
    s = run_dig(d, Verdict(status="OBSERVED"))
    assert s["OBSERVED"] == 2 and s["probes"] == 2 and s["resolved_pct"] == 100


def test_budget_and_termination_when_unresolved():
    d = db()
    store_initial(d, [draft(str(i)) for i in range(5)], 1)
    assert run_dig(d, Verdict(status="INFERRED", confidence=.4), budget=3)["probes"] == 3
    d = db()
    store_initial(d, [draft("a")], 1)
    assert run_dig(d, Verdict(status="INFERRED", confidence=.4))["probes"] == 1  # a pass that settles nothing ends


def test_failed_probe_leaves_claim_inferred():
    d = db()
    store_initial(d, [draft()], 1)
    assert run_dig(d, Verdict(status="OBSERVED"), trace_result=None)["INFERRED"] == 1


def test_muse_audit_catches_sealed_paths():
    audit('{"tool":"read_file","path":"/tmp/x/app.py"}')
    for bad in ('{"path":"/Users/k/lazarus-sealed/relic-src/main.go"}', 'cat heldout/set.jsonl.age', 'grep AGE_KEY_SOURCE /x', 'read /Users/k/.claude/projects/x.jsonl'):
        with pytest.raises(SealBreach):
            audit(bad)


def test_meta_retries_then_fails_and_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(meta, "LOG_DIR", tmp_path)
    calls = []
    def bad(p):
        calls.append(p)
        return {"output": []}
    with pytest.raises(meta.MetaError):
        meta.spark("c", "i", "x", Verdict, post=bad)
    assert len(calls) == 3 and len(list(tmp_path.iterdir())) == 3


def test_meta_parses_documented_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(meta, "LOG_DIR", tmp_path)
    resp = {"output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": '{"status":"REFUTED"}'}]}]}
    assert meta.spark("c", "i", "x", Verdict, post=lambda p: resp).status == "REFUTED"
