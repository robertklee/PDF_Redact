from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pdf_redact.main import create_app
from pdf_redact.security import hostname_of


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("127.0.0.1:8765", "127.0.0.1"),
        ("localhost", "localhost"),
        ("[::1]:8765", "::1"),
        ("Evil.example.com:80", "evil.example.com"),
    ],
)
def test_hostname_of(header: str, expected: str) -> None:
    assert hostname_of(header) == expected


def test_health_with_token(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["engine"].startswith("PyMuPDF")


def test_api_requires_token(settings) -> None:
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/health").status_code == 401
        assert c.get("/api/health", headers={"X-Session-Token": "wrong"}).status_code == 401


def test_rejects_foreign_host(client: TestClient) -> None:
    resp = client.get("/api/health", headers={"Host": "attacker.example:8765"})
    assert resp.status_code == 403


def test_security_headers(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Cache-Control"] == "no-store"
