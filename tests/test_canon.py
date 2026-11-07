from core.canon import canon_body, canon_equal
from core.schemas import Response as R


def test_key_order_and_spacing_ignored():
    assert canon_equal(R(status=200, body='{"a":1, "b":2}\n'), R(status=200, body={"b": 2, "a": 1}))

def test_whitespace_inside_strings_is_data():
    assert not canon_equal(R(status=200, body={"c": "x "}), R(status=200, body={"c": "x"}))

def test_status_differs():
    assert not canon_equal(R(status=200, body={}), R(status=201, body={}))

def test_ignored_headers_and_case():
    a = R(status=200, headers={"Date": "x", "Server": "go", "Content-Type": "application/json"}, body={})
    b = R(status=200, headers={"content-type": "application/json", "content-length": "9"}, body={})
    assert canon_equal(a, b)

def test_allow_listed_headers_compared():
    assert not canon_equal(R(status=301, headers={"Location": "/a"}), R(status=301, headers={"location": "/b"}))
    assert not canon_equal(R(status=200, headers={"content-type": "text/plain"}), R(status=200, headers={"content-type": "application/json"}))

def test_int_is_not_float():
    assert canon_body({"a": 1}) != canon_body({"a": 1.0})

def test_non_json_body():
    assert canon_body(" plain\n") == "plain"
    assert canon_body(None) == ""
