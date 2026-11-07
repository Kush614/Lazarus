"""If this fails, stop: it is the demo's credibility."""
import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
PY = [p for p in ROOT.rglob("*.py") if not {".venv", "tests"} & set(p.relative_to(ROOT).parts)]


def _users(pattern):
    return {str(p.relative_to(ROOT)) for p in PY if re.search(pattern, p.read_text())}


def test_only_gate_touches_heldout():
    assert _users(r"""AGE_KEY_HELDOUT|set\.jsonl|heldout/|/\s*["']heldout["']""") <= {"core/gate.py"}


def test_only_reveal_touches_source():
    assert _users(r"AGE_KEY_SOURCE|source\.tar") <= {"scripts/reveal.py"}


def test_no_plaintext_secrets_in_tree():
    tracked = [p for p in ROOT.rglob("*") if p.is_file() and not {".venv", ".git", "__pycache__", ".pytest_cache"} & set(p.relative_to(ROOT).parts)]
    assert not [p for p in tracked if p.suffix == ".go" or p.name in ("set.jsonl", "source.tar", "gen_data.py")]
