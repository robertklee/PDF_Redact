"""In-process storage for uploaded documents and redacted outputs.

Files live in a private temporary directory that is removed on shutdown. Nothing is persisted.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from .core import ENGINE_LOCK


@dataclass
class StoredDocument:
    id: str
    filename: str
    path: Path
    size: int
    sha256: str
    doc: pymupdf.Document  # kept open for page text extraction
    password: str | None = None
    text_cache: dict[int, dict] = field(default_factory=dict)
    outputs: list[str] = field(default_factory=list)

    @property
    def locked(self) -> bool:
        """Encrypted with a user password that has not been supplied yet."""
        return self.doc.is_encrypted


@dataclass
class StoredOutput:
    id: str
    document_id: str
    filename: str
    path: Path
    size: int
    sha256: str
    # Audit record of the application, including the removed text (see core/report.py).
    audit: dict[str, Any] | None = None


class Store:
    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="pdf-redact-"))
        self._lock = threading.Lock()
        self._documents: dict[str, StoredDocument] = {}
        self._outputs: dict[str, StoredOutput] = {}
        atexit.register(self.close)

    def new_path(self, suffix: str = ".pdf") -> Path:
        return self.root / f"{uuid.uuid4().hex}{suffix}"

    def add_document(self, document: StoredDocument) -> None:
        with self._lock:
            self._documents[document.id] = document

    def document(self, document_id: str) -> StoredDocument:
        with self._lock:
            return self._documents[document_id]

    def add_output(self, output: StoredOutput) -> None:
        with self._lock:
            self._outputs[output.id] = output
            self._documents[output.document_id].outputs.append(output.id)

    def output(self, output_id: str) -> StoredOutput:
        with self._lock:
            return self._outputs[output_id]

    def remove_document(self, document_id: str) -> None:
        with self._lock:
            document = self._documents.pop(document_id)
            outputs = [self._outputs.pop(o) for o in document.outputs if o in self._outputs]
        with ENGINE_LOCK:
            document.doc.close()
        for path in [document.path, *(o.path for o in outputs)]:
            path.unlink(missing_ok=True)

    def close(self) -> None:
        with self._lock:
            documents = list(self._documents.values())
            self._documents.clear()
            self._outputs.clear()
        with ENGINE_LOCK:
            for document in documents:
                if not document.doc.is_closed:
                    document.doc.close()
        shutil.rmtree(self.root, ignore_errors=True)
        atexit.unregister(self.close)
