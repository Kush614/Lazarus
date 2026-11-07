from core.diff import unified
from core.schemas import Response as R


def test_shows_changed_field():
    d = unified(R(status=200, body={"x": 1, "y": 2}), R(status=200, body={"x": 9, "y": 2}))
    assert '-    "x": 1' in d and '+    "x": 9' in d and "y" not in "".join(l for l in d.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---")))

def test_equal_is_empty():
    assert unified(R(status=200, body={"a": 1}), R(status=200, body={"a": 1})) == ""
