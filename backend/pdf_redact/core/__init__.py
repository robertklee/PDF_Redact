"""PDF engine: text geometry, redaction and verification built on PyMuPDF."""

from __future__ import annotations

import threading

# MuPDF is not thread-safe, even across separate documents. All engine calls from the web layer
# must hold this lock.
ENGINE_LOCK = threading.RLock()
