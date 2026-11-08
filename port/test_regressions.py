from fastapi.testclient import TestClient

from app import app


def _get_no_redirect(client, path):
    try:
        return client.get(path, follow_redirects=False)
    except TypeError:
        return client.get(path, allow_redirects=False)


def test_healthz_trailing_slash_returns_404_not_found():
    client = TestClient(app, raise_server_exceptions=False)
    resp = _get_no_redirect(client, "/healthz/")
    assert resp.status_code == 404
    assert resp.json() == {"error": "not found"}
