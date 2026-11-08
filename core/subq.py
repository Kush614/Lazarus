"""SubQ Snap: a fast yes/no judge. It answers with the probability that the answer is yes.

Used as a second opinion, never as the decision itself: the oracle's byte comparison
decides whether two programs differ; SubQ is asked whether a difference looks like a real
behaviour change rather than noise, and its answer is shown next to the evidence.
Two keys: calls alternate between SUBQ_API_KEY and SUBQ_API_KEY_BACKUP (SUBQ_KEY_MODE=alternate, the
default) so load and usage are split across both; either key falls back to the other when refused
(expired, out of credit, rate-limited). SUBQ_KEY_MODE=failover uses the backup only on refusal.
Every call is logged to logs/meta/ like the Meta calls.
"""
import json
import os
import pathlib
import time

import httpx

URL = "https://api.subq.ai/v1/systemone"
MODEL = "subq-snap-1.1"
LOG_DIR = pathlib.Path(__file__).parent.parent / "logs" / "meta"


class SubQError(RuntimeError):
    pass


_turn = {"n": 0}


def _keys() -> list[tuple[str, str]]:
    """(label, key) in the order to try them for this call."""
    ks = [(label, k) for label, k in (("primary", os.getenv("SUBQ_API_KEY")), ("backup", os.getenv("SUBQ_API_KEY_BACKUP"))) if k]
    if len(ks) == 2 and os.getenv("SUBQ_KEY_MODE", "alternate") == "alternate":
        _turn["n"] += 1
        if _turn["n"] % 2 == 0:
            ks.reverse()
    return ks


def yes_probability(state: str, question: str, yes: str, no: str, call: str = "subq", post=None) -> float:
    """Probability in [0, 1] that the answer to `question` about `state` is yes."""
    body = {"model": MODEL, "state": state[:6000],
            "questions": {"q": {"type": "noul", "instructions": question, "criteria": {"yes": yes, "no": no}}}}
    post = post or (lambda key: httpx.post(URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=30))
    keys, last = _keys(), "no SUBQ_API_KEY set"
    for i, (label, key) in enumerate(keys):
        started = time.time()
        try:
            r = post(key)
        except httpx.HTTPError as e:
            last = f"{type(e).__name__}"
            continue
        _log(call, body, r.status_code, r.text[:2000], backup=label == "backup", key=label, failover=i > 0,
             seconds=round(time.time() - started, 2))
        if r.status_code in (401, 402, 403, 429):
            last = f"{label} key refused ({r.status_code})"
            continue
        if r.status_code != 200:
            raise SubQError(f"SubQ returned {r.status_code}")
        return float(r.json()["answers"]["q"]["noul"])
    raise SubQError(last)


def _log(call, body, status, text, backup, key=None, failover=False, seconds=None):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / f"{call}_{time.time_ns()}.json").write_text(json.dumps(
        {"call": call, "provider": "subq", "model": MODEL, "request": body, "status": status, "response": text,
         "backup_key": backup, "key": key or ("backup" if backup else "primary"), "failover": failover,
         "seconds": seconds, "at": time.time()}))


def console(limit: int = 25, get=None) -> dict:
    """Our view of SubQ usage, from every logged call (SubQ has no usage API): per key, per call site, recent calls."""
    keys: dict = {}
    sites: dict = {}
    recent = []
    for f in sorted(LOG_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            d = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        if d.get("provider") != "subq":
            continue
        label = d.get("key") or ("backup" if d.get("backup_key") else "primary")
        try:
            resp = json.loads(d.get("response") or "{}")
        except ValueError:
            resp = {}
        u = resp.get("usage") or {}
        ok = int(d.get("status") or 0) == 200
        k = keys.setdefault(label, {"key": label, "calls": 0, "ok": 0, "refused": 0, "errors": 0, "input_tokens": 0,
                                    "output_tokens": 0, "seconds": [], "failovers": 0, "last_at": None})
        k["calls"] += 1
        k["ok"] += ok
        k["refused"] += int(d.get("status") or 0) in (401, 402, 403, 429)
        k["errors"] += (not ok) and int(d.get("status") or 0) not in (401, 402, 403, 429)
        k["input_tokens"] += int(u.get("input_tokens") or 0)
        k["output_tokens"] += int(u.get("output_tokens") or 0)
        k["failovers"] += bool(d.get("failover"))
        k["last_at"] = d.get("at") or f.stat().st_mtime
        if d.get("seconds") is not None:
            k["seconds"].append(d["seconds"])
        sites[d.get("call", "?")] = sites.get(d.get("call", "?"), 0) + 1
        req = d.get("request") or {}
        q = ((req.get("questions") or {}).get("q") or {}) if isinstance(req, dict) else {}
        p = ((resp.get("answers") or {}).get("q") or {}).get("noul")
        recent.append({"at": d.get("at") or f.stat().st_mtime, "call": d.get("call"), "key": label, "status": d.get("status"),
                       "question": q.get("instructions"), "yes_probability": p, "input_tokens": u.get("input_tokens"),
                       "output_tokens": u.get("output_tokens"), "seconds": d.get("seconds"), "failover": d.get("failover", False)})
    for k in keys.values():
        s = k.pop("seconds")
        k["avg_seconds"] = round(sum(s) / len(s), 2) if s else None
    try:
        r = (get or (lambda: httpx.get("https://api.subq.ai/v1/models", timeout=10,
                                       headers={"Authorization": f"Bearer {os.getenv('SUBQ_API_KEY', '')}"})))()
        models = [m.get("id") for m in r.json().get("data", [])]
    except (httpx.HTTPError, ValueError, AttributeError):
        models = []
    return {"model_in_use": MODEL, "models_available": models, "key_mode": os.getenv("SUBQ_KEY_MODE", "alternate"),
            "keys_configured": [lb for lb, k in (("primary", os.getenv("SUBQ_API_KEY")), ("backup", os.getenv("SUBQ_API_KEY_BACKUP"))) if k], "keys": list(keys.values()), "by_call_site": sites,
            "recent": list(reversed(recent))[:limit]}


def genuine_divergence(original: dict, port: dict, request: dict, post=None) -> float:
    state = json.dumps({"request": request, "original_answer": original, "port_answer": port})[:6000]
    return yes_probability(state, "Do these two programs behave differently for this request, in a way a user of the service would notice?",
                           "The status code or the meaningful content of the body differs.",
                           "The answers are equivalent, or the difference is only a timeout, transport error or formatting noise.",
                           call="subq_divergence", post=post)
