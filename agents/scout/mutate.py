"""Generic input mutations for differential testing. Nothing here knows about any particular
program: the variants come from recorded requests plus edge cases common to all software."""
import copy
import hashlib
import json
import re

from core.schemas import Request


def _string_variants(s: str):
    yield f"{s} ", "trailing space"
    yield f" {s}", "leading space"
    yield s.lower() if s != s.lower() else s.upper(), "changed case"
    yield "", "empty string"


def _number_variants(n):
    yield 0, "zero"
    yield -1, "negative"
    yield n + 1, "off by one"
    yield 10**9, "very large"
    yield n + .5, "fraction"
    yield str(n), "number as text"


def _walk(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items():
            yield path + (k,), v
            yield from _walk(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node[:2]):
            yield path + (i,), v
            yield from _walk(v, path + (i,))


def _set(body, path, value):
    out = copy.deepcopy(body)
    node = out
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return out


def _drop(body, path):
    out = copy.deepcopy(body)
    node = out
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return out


def variants(req: Request):
    """Yields (mutated request, what changed)."""
    if not req.path.endswith("/"):
        yield req.model_copy(update={"path": req.path + "/"}), "path: trailing slash"
    if req.path != req.path.lower():
        yield req.model_copy(update={"path": req.path.lower()}), "path: lower case"
    body = req.body
    if not isinstance(body, dict | list):
        return
    for path, value in _walk(body):
        where = ".".join(str(p) for p in path)
        if isinstance(value, bool):
            continue
        if isinstance(value, str):
            for v, label in _string_variants(value):
                yield req.model_copy(update={"body": _set(body, path, v)}), f"{where}: {label}"
        elif isinstance(value, int | float):
            for v, label in _number_variants(value):
                yield req.model_copy(update={"body": _set(body, path, v)}), f"{where}: {label}"
        elif isinstance(value, list):
            yield req.model_copy(update={"body": _set(body, path, [])}), f"{where}: empty list"
        yield req.model_copy(update={"body": _set(body, path, None)}), f"{where}: null"
        if isinstance(path[-1], str):
            yield req.model_copy(update={"body": _drop(body, path)}), f"{where}: missing"


def request_hash(req: Request) -> str:
    return hashlib.sha256(json.dumps(req.model_dump(), sort_keys=True).encode()).hexdigest()


def matches(endpoint: str, req: Request) -> bool:
    """`POST /a/{b}` against a concrete request."""
    method, _, template = endpoint.partition(" ")
    return method == req.method and re.fullmatch(re.sub(r"\{[^/]+\}", "[^/]+", template), req.path.split("?")[0]) is not None


def plan(traces: list[Request], weak_endpoints: list[str], seen: set[str], budget: int) -> list[tuple[Request, str]]:
    """Weak endpoints first, then an even share per recorded request, so one big body cannot use the whole budget."""
    ranked = sorted(traces, key=lambda r: 0 if any(matches(e, r) for e in weak_endpoints) else 1)
    pools = [variants(r) for r in ranked]
    out: list[tuple[Request, str]] = []
    taken = set(seen)
    while pools and len(out) < budget:
        alive = []
        for pool in pools:
            if len(out) >= budget:
                break
            for candidate, label in pool:
                h = request_hash(candidate)
                if h not in taken:
                    taken.add(h)
                    out.append((candidate, label))
                    alive.append(pool)
                    break
        pools = alive
    return out
