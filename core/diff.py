"""Readable unified diff between two responses, in canonical form."""
import difflib
import json

from core.canon import canon_response
from core.schemas import Response


def _lines(r: Response) -> list[str]:
    c = canon_response(r)
    try:
        c["body"] = json.loads(c["body"])
    except ValueError:
        pass
    return json.dumps(c, sort_keys=True, indent=2, ensure_ascii=False).splitlines()


def unified(original: Response, port: Response) -> str:
    return "\n".join(difflib.unified_diff(_lines(original), _lines(port), "original", "port", lineterm=""))
