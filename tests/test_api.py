"""Flask API tests (uses Flask's test client, no real server needed)."""

import pytest

from app import app
from mirror.examples import EXAMPLES


@pytest.fixture
def client():
    return app.test_client()


def test_examples_endpoint(client):
    data = client.get("/api/examples").get_json()
    assert [e["id"] for e in data] == [e["id"] for e in EXAMPLES]


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e["id"])
def test_visualize_examples(client, example):
    resp = client.post("/api/visualize", json={"code": example["code"]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["graph"]["nodes"] and body["trace"]["steps"]
    assert body["trace"]["error"] is None


def test_visualize_syntax_error(client):
    body = client.post("/api/visualize", json={"code": "if True\n  x = 1\n"}).get_json()
    assert body["graph"] is None
    assert body["trace"]["error"]["kind"] == "syntax"


def test_visualize_rejects_empty_and_huge_code(client):
    assert client.post("/api/visualize", json={"code": "  "}).status_code == 400
    assert client.post("/api/visualize", json={"code": "x=1\n" * 5000}).status_code == 400
    assert client.post("/api/visualize", data="not json").status_code == 400


def test_server_binds_to_localhost_only():
    source = open("app.py").read()
    assert 'host="127.0.0.1"' in source
