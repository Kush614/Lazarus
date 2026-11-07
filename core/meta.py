"""The only path to Muse Spark. Every request and response is written to logs/meta/."""
import json
import os
import pathlib
import time

import httpx
from pydantic import BaseModel, ValidationError

BASE_URL = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"
LOG_DIR = pathlib.Path(__file__).parent.parent / "logs" / "meta"
MAX_ATTEMPTS = 3


class MetaError(RuntimeError):
    """Model failed after bounded retries; callers surface FAILED."""


def _output_text(resp: dict) -> str:
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    return c["text"]
    raise ValueError("no output_text in response")


def _log(call: str, payload: dict, response, error: str | None) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / f"{call}_{time.time_ns()}.json").write_text(
        json.dumps({"call": call, "request": payload, "response": response, "error": error}, indent=2))


def spark(call: str, instructions: str, user_input: str, schema: type[BaseModel], post=None) -> BaseModel:
    payload = {
        "model": MODEL,
        "instructions": instructions,
        "input": user_input,
        "text": {"format": {"type": "json_schema", "name": schema.__name__, "schema": schema.model_json_schema()}},
    }
    post = post or _post
    last = None
    for attempt in range(MAX_ATTEMPTS):
        resp = None
        try:
            resp = post(payload)
            parsed = schema.model_validate_json(_output_text(resp))
            _log(call, payload, resp, None)
            return parsed
        except (httpx.HTTPError, ValueError, KeyError, ValidationError) as e:
            last = f"{type(e).__name__}: {e}"
            _log(call, payload, resp, last)
            time.sleep(2 ** attempt if post is _post else 0)
    raise MetaError(f"{call} failed after {MAX_ATTEMPTS} attempts: {last}")


def _post(payload: dict) -> dict:
    r = httpx.post(f"{BASE_URL}/responses", json=payload, timeout=180,
                   headers={"Authorization": f"Bearer {os.environ['META_API_KEY']}"})
    r.raise_for_status()
    return r.json()
