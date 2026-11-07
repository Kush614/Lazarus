"""Canonical form used for every original-vs-port comparison."""
import json
from typing import Any

from core.schemas import Response

HEADER_ALLOW_LIST = ("content-type", "location")


def canon_body(body: Any) -> str:
    """Sorted keys and no insignificant whitespace. Whitespace inside strings is
    data and must survive."""
    if body is None:
        return ""
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return body.strip()
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canon_response(r: Response) -> dict:
    lowered = {k.lower(): v for k, v in r.headers.items()}
    return {
        "status": r.status,
        "headers": {h: lowered[h] for h in HEADER_ALLOW_LIST if h in lowered},
        "body": canon_body(r.body),
    }


def canon_equal(a: Response, b: Response) -> bool:
    return canon_response(a) == canon_response(b)
