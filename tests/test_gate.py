import json

from core import gate
from core.sandbox import StaticTarget
from core.schemas import PortVersion


def pv(eq, version=1):
    return PortVersion(version=version, commit="c", heldout_equivalence=eq, regressions=[], status="ADOPTED")


def test_scores_and_exposes_no_contents(fake_url, sealed_set):
    url, F = fake_url
    F.routes = {"/0": (200, {"n": 0}), "/1": (200, {"n": 1}), "/2": (200, {"n": 999})}
    r = gate.evaluate(StaticTarget(url), 2, path=sealed_set[0], key=sealed_set[1])
    assert r.version.heldout_equivalence == 0.5 and sorted(r.matched_ids) == ["HO-0", "HO-1"]
    dumped = r.model_dump_json()
    assert "expected_response" not in dumped and '"path"' not in dumped and '"/2"' not in dumped


def test_regression_blocks_even_with_higher_score(fake_url, sealed_set):
    url, F = fake_url
    F.routes = {f"/{i}": (200, {"n": i}) for i in (1, 2, 3)}
    r = gate.evaluate(StaticTarget(url), 3, parent=pv(0.5), immune_ids=["HO-0"], path=sealed_set[0], key=sealed_set[1])
    assert r.version.heldout_equivalence == 0.75 and r.version.regressions == ["HO-0"]
    assert gate.settle(r, approved=True, decided_by="user").status == "ROLLED_BACK"


def test_equal_score_rolls_back(fake_url, sealed_set):
    url, F = fake_url
    F.routes = {"/0": (200, {"n": 0}), "/1": (200, {"n": 1})}
    r = gate.evaluate(StaticTarget(url), 3, parent=pv(0.5), path=sealed_set[0], key=sealed_set[1])
    assert gate.settle(r, True, "auto").status == "ROLLED_BACK"


def test_improvement_needs_approval(fake_url, sealed_set):
    url, F = fake_url
    F.routes = {"/0": (200, {"n": 0}), "/1": (200, {"n": 1}), "/2": (200, {"n": 2})}
    r = gate.evaluate(StaticTarget(url), 3, parent=pv(0.5), immune_ids=["HO-0"], path=sealed_set[0], key=sealed_set[1])
    assert gate.settle(r, True, "user").status == "ADOPTED"
    assert gate.settle(r, False, "user").status == "ROLLED_BACK"


def test_dead_target_is_failed_never_a_match(sealed_set):
    r = gate.evaluate(StaticTarget("http://127.0.0.1:9"), 1, path=sealed_set[0], key=sealed_set[1])
    assert r.failed == 4 and r.version.heldout_equivalence == 0


def test_hash_is_of_plaintext(sealed_set):
    assert len(gate.heldout_hash(*sealed_set)) == 64
