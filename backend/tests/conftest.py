from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pdf_redact.config import Settings
from pdf_redact.main import create_app

TOKEN = "test-token"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        token=TOKEN,
        allowed_hosts=frozenset({"testserver", "127.0.0.1", "localhost"}),
        static_dir=None,
    )


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings), headers={"X-Session-Token": TOKEN}) as c:
        yield c
