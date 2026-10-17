"""Time the API on a large document: python -m tests.bench [pages].

Not part of the test suite. The document has a full page of text on every page, personal
information on every fifth page and an image on every tenth page.
"""

from __future__ import annotations

import random
import sys
import time
from contextlib import contextmanager

import pymupdf

from .corpus import SECRET, _pattern_pixmap

WORDS = (  # noqa: SIM905
    "the of and to in a is that for it as was with be by on not he this are or his from at which "
    "but have an they you were her she there been one all we their has would when if so no what up "
    "out who them some could more into time only new about then its these two may first any like"
).split()


def large_document(pages: int, seed: int = 1) -> bytes:
    rng = random.Random(seed)
    doc = pymupdf.open()
    pixmap = _pattern_pixmap()
    for i in range(pages):
        page = doc.new_page()
        lines = [" ".join(rng.choices(WORDS, k=14)).capitalize() + "." for _ in range(44)]
        if i % 5 == 0:
            lines[10] = (
                f"Contact jane.doe{i}@example.com or (202) 555-{i % 10000:04d} about {SECRET}."
            )
            lines[20] = "SSN: 123-45-6789, card 4111 1111 1111 1111."
        page.insert_text((60, 60), "\n".join(lines), fontsize=10, lineheight=1.5)
        if i % 10 == 0:
            page.insert_image(pymupdf.Rect(360, 680, 540, 770), pixmap=pixmap)
    return doc.tobytes(garbage=3, deflate=True)


@contextmanager
def timed(label: str):
    start = time.perf_counter()
    yield
    print(f"{label:<34} {time.perf_counter() - start:7.2f} s", flush=True)


def main(pages: int) -> None:
    from fastapi.testclient import TestClient

    from pdf_redact.config import Settings
    from pdf_redact.main import create_app

    with timed(f"generate {pages} pages"):
        data = large_document(pages)
    print(f"{'size':<34} {len(data) / 1e6:7.1f} MB")
    settings = Settings(token="t", allowed_hosts=frozenset({"testserver"}), static_dir=None)
    with TestClient(create_app(settings), headers={"X-Session-Token": "t"}) as client:
        with timed("open"):
            doc = client.post("/api/documents", content=data).json()
        base = f"/api/documents/{doc['id']}"
        with timed("text of page 1"):
            client.get(f"{base}/pages/0/text").raise_for_status()
        with timed("search, first (extracts all text)"):
            hits = client.post(f"{base}/search", json={"query": SECRET}).json()["matches"]
        with timed("search, second"):
            client.post(f"{base}/search", json={"query": "could more"}).raise_for_status()
        with timed("search, regex"):
            client.post(f"{base}/search", json={"query": r"\bth\w+", "mode": "regex"})
        detectors = [d["id"] for d in client.get("/api/detectors").json()]
        with timed("detect, all detectors"):
            found = client.post(f"{base}/detect", json={"categories": detectors}).json()
        print(f"{'hits':<34} {len(hits):7} search, {len(found['matches'])} detect")
        marks = [
            {"id": f"m{i}", "page": h["page"], "kind": "text", "rects": h["rects"]}
            for i, h in enumerate(hits)
        ]
        marks.append({"id": "area", "page": 0, "kind": "area", "rects": [[350, 670, 550, 780]]})
        with timed(f"apply + verify, {len(marks)} marks"):
            out = client.post(
                f"{base}/apply", json={"marks": marks, "searchTerms": [SECRET]}
            ).json()
        print(f"{'verification':<34} {out['verification']['counts']}")
        with timed("report"):
            client.get(f"/api/outputs/{out['id']}/report").raise_for_status()
        with timed("marked copy"):
            client.post(f"{base}/marked", json={"marks": marks}).raise_for_status()


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000)
