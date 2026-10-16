from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent


def _default_static_dir() -> Path | None:
    candidates = []
    if env := os.environ.get("PDF_REDACT_STATIC"):
        candidates.append(Path(env))
    candidates += [_PACKAGE_DIR / "static", _PACKAGE_DIR.parents[1] / "frontend" / "dist"]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    return None


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8765
    # Every /api request must carry this token in the X-Session-Token header. It prevents other
    # web pages (or local users' browsers) from driving the API of a running instance.
    token: str = field(
        default_factory=lambda: os.environ.get("PDF_REDACT_TOKEN") or secrets.token_urlsafe(24)
    )
    # Rejecting unexpected Host headers defeats DNS-rebinding attacks against the local server.
    allowed_hosts: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})
    max_upload_bytes: int = 512 * 1024 * 1024
    static_dir: Path | None = field(default_factory=_default_static_dir)
