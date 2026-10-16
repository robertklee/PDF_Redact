from __future__ import annotations

import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import Settings

TOKEN_HEADER = "x-session-token"

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def hostname_of(host_header: str) -> str:
    """Strip the port from a Host header value, handling bracketed IPv6 literals."""
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def install_security(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):
        if hostname_of(request.headers.get("host", "")) not in settings.allowed_hosts:
            return JSONResponse({"detail": "Host not allowed"}, status_code=403)
        if request.url.path.startswith("/api/"):
            supplied = request.headers.get(TOKEN_HEADER, "")
            if not secrets.compare_digest(supplied.encode(), settings.token.encode()):
                return JSONResponse({"detail": "Missing or invalid session token"}, 401)
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response
