"""The oracle and everything it imports must not reach digger, prober or the port source."""
import ast
import pathlib

ROOT = pathlib.Path(__file__).parent.parent
ORACLE_SIDE = [*(ROOT / "agents/oracle").rglob("*.py"), *(ROOT / "core").rglob("*.py")]
FORBIDDEN = ("agents.digger", "agents.prober", "port")


def _imports(path):
    for n in ast.walk(ast.parse(path.read_text())):
        if isinstance(n, ast.Import):
            yield from (a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            yield n.module


def test_oracle_side_imports_are_clean():
    bad = [(str(p.relative_to(ROOT)), m) for p in ORACLE_SIDE for m in _imports(p)
           if any(m == f or m.startswith(f + ".") for f in FORBIDDEN)]
    assert not bad


def test_oracle_never_reads_hypotheses():
    for p in (ROOT / "agents/oracle").rglob("*.py"):
        assert "hypotheses" not in p.read_text(), p
