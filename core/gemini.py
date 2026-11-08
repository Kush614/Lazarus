"""Gemini via the Interactions API (plain HTTPS, so retries and timeouts are ours).

Roles: gemini-4-argon leads (ports, audit memos) when the account has quota for it; the
call falls back down the chain and reports the model that actually answered, so the UI
never credits a model that did not produce the text. Every call is logged to logs/meta/.
"""
import json
import os
import pathlib
import time

import httpx

URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
ARGON = "gemini-4-argon"
FLASH = "gemini-3.8-flash"
LITE = "gemini-3.5-flash-lite"
LEAD = [ARGON, LITE]  # 3.8 Flash answers in 60-120 s on this account; too slow for a live demo
FAST = [LITE]
LOG_DIR = pathlib.Path(__file__).parent.parent / "logs" / "meta"
TIMEOUTS = {ARGON: 240.0, FLASH: 120.0, LITE: 60.0}


class GeminiError(RuntimeError):
    pass


def _text(d: dict) -> str:
    for step in d.get("steps") or []:
        if step.get("type") == "model_output":
            return "".join(c.get("text", "") for c in step.get("content", []) if c.get("type") == "text")
    return ""


def _one(call: str, model: str, prompt: str, thinking: str, post=None) -> str:
    started, text, err = time.time(), "", None
    body = {"model": model, "input": prompt}
    if model == ARGON:
        body["generation_config"] = {"thinking_level": thinking}
    try:
        if post:
            r = post(body)
        else:
            r = httpx.post(URL, json=body, timeout=TIMEOUTS.get(model, 120.0),
                           headers={"x-goog-api-key": os.environ.get("GEMINI_API_KEY", "")})
        d = r.json()
        if r.status_code != 200:
            err = f"{r.status_code}: {(d.get('error') or {}).get('message', '')[:200]}"
        else:
            text = _text(d)
            err = None if text else "empty output"
    except (httpx.HTTPError, ValueError) as e:
        err = f"{type(e).__name__}: {str(e)[:200]}"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / f"gemini_{call}_{time.time_ns()}.json").write_text(json.dumps(
        {"call": call, "provider": "google", "model": model, "prompt": prompt[:20000], "output": text[:20000],
         "error": err, "seconds": round(time.time() - started, 1)}))
    if err:
        raise GeminiError(f"{model} {err}")
    return text


def ask(call: str, prompt: str, chain=LEAD, thinking: str = "medium", post=None) -> tuple[str, str]:
    """Returns (text, model that answered). Raises GeminiError if every model in the chain failed."""
    if not os.getenv("GEMINI_API_KEY") and post is None:
        raise GeminiError("GEMINI_API_KEY is not set")
    errors = []
    for model in chain:
        try:
            return _one(call, model, prompt, thinking, post), model
        except GeminiError as e:
            errors.append(str(e))
    raise GeminiError("; ".join(errors))


def ask_json(call: str, prompt: str, chain=LEAD, thinking: str = "medium", post=None):
    """Returns (parsed JSON, model). Takes the first JSON object or array in the reply."""
    text, model = ask(call, prompt + "\n\nReply with JSON only, no prose, no code fences.", chain, thinking, post)
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise GeminiError(f"{model} returned no JSON")
    try:
        return json.JSONDecoder().raw_decode(text[min(starts):])[0], model
    except ValueError as e:
        raise GeminiError(f"{model} returned bad JSON: {e}")
