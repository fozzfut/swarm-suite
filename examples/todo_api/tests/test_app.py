"""Minimal happy-path tests. Intentionally incomplete -- review-swarm's
test-quality expert will note the gap (no SQLi test, no error-path coverage,
no test for delete_todo)."""

from __future__ import annotations

import pytest

from todo_api.app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}


def test_list_empty(client):
    r = client.get("/todos")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)
