from __future__ import annotations

import argparse
import threading
import webbrowser
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings
from .security import install_security

health_router = APIRouter(prefix="/api")


@health_router.get("/health")
def health() -> dict:
    import pymupdf

    return {"status": "ok", "version": __version__, "engine": f"PyMuPDF {pymupdf.__version__}"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(
        title="PDF Redact",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    install_security(app, settings)
    app.include_router(health_router)

    if settings.static_dir is not None:
        app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="ui")
    return app


def cli(argv: list[str] | None = None) -> None:
    import uvicorn

    parser = argparse.ArgumentParser(prog="pdf-redact", description="Local PDF redaction tool")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    args = parser.parse_args(argv)

    settings = Settings(port=args.port)
    app = create_app(settings)
    url = f"http://{settings.host}:{settings.port}/#token={settings.token}"
    if settings.static_dir is None:
        print("Warning: UI build not found; run `npm run build` in frontend/ (API only).")
    print(f"PDF Redact {__version__} running at:\n  {url}\nPress Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    cli()
