"""PDF engine: text geometry, redaction and verification built on PyMuPDF."""

from __future__ import annotations

import threading

import pymupdf

# MuPDF reports recoverable problems (e.g. a damaged content stream) through a Python callback
# that prints them. Undecodable bytes in such a message make the print fail, which turns the
# recoverable problem into an exception, so keep them off the console.
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)


class _EngineLock:
    """Re-entrant lock that also discards the MuPDF messages collected while it was held."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._depth = 0

    def __enter__(self) -> _EngineLock:
        self._lock.acquire()
        self._depth += 1
        return self

    def __exit__(self, *exc: object) -> None:
        self._depth -= 1
        if self._depth == 0:
            pymupdf.TOOLS.reset_mupdf_warnings()
        self._lock.release()


# MuPDF is not thread-safe, even across separate documents. All engine calls from the web layer
# must hold this lock.
ENGINE_LOCK = _EngineLock()
