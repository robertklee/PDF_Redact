from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import HTTPException

from pdf_redact import api
from pdf_redact.core.progress import Cancelled, report, tracking
from pdf_redact.jobs import NDJSON, Job, Jobs
from pdf_redact.main import create_app
from tests import corpus
from tests.conftest import TOKEN
from tests.corpus import SECRET
from tests.helpers import mupdf_text
from tests.test_api import upload

STREAM = {"Accept": NDJSON}


def events(res) -> list[dict]:
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith(NDJSON)
    return [json.loads(line) for line in res.text.splitlines()]


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def update(self, phase: str, done: int, total: int) -> None:
        self.calls.append((phase, done, total))


def test_report_goes_to_the_current_tracker_only() -> None:
    report("Nobody listens")
    recorder = Recorder()
    with tracking(recorder):
        report("Reading", 1, 3)
        report("Thinking")
    report("Nobody listens")
    assert recorder.calls == [("Reading", 1, 3), ("Thinking", 0, 0)]


def test_job_outcomes() -> None:
    def work():
        report("Working", 1, 2)
        return corpus_model()

    job = Job()
    job.run(work)
    assert job.finished.is_set()
    assert job.progress() == ("Working", 1, 2)
    assert job.outcome == {"type": "result", "result": {"id": "x", "pageCount": 1}}

    job = Job()
    job.cancel()
    job.run(work)
    assert job.outcome == {"type": "cancelled"}

    def refused():
        raise HTTPException(422, "No")

    job = Job()
    job.run(refused)
    assert job.outcome == {"type": "error", "status": 422, "detail": "No"}

    def broken():
        raise RuntimeError("secret internals")

    job = Job()
    job.run(broken)
    assert job.outcome == {"type": "error", "status": 500, "detail": "Internal Server Error"}


def test_job_raises_cancelled_at_the_next_report() -> None:
    job = Job()
    with tracking(job):
        report("Working", 0, 2)
        job.cancel()
        with pytest.raises(Cancelled):
            report("Working", 1, 2)


def test_jobs_registry() -> None:
    jobs = Jobs()
    first, second = Job(), Job()
    jobs.add(first)
    jobs.add(second)
    jobs.cancel(first.id)
    with pytest.raises(Cancelled):
        first.update("x", 0, 0)
    second.update("x", 0, 0)
    jobs.cancel_all()
    with pytest.raises(Cancelled):
        second.update("x", 0, 0)
    jobs.remove(first.id)
    with pytest.raises(KeyError):
        jobs.cancel(first.id)


def corpus_model():
    from pdf_redact.models import ApiModel

    class Small(ApiModel):
        id: str
        page_count: int

    return Small(id="x", page_count=1)


def test_streamed_search_matches_the_plain_response(client) -> None:
    doc_id = upload(client, corpus.many_pages(3)).json()["id"]
    url = f"/api/documents/{doc_id}/search"
    plain = client.post(url, json={"query": SECRET}).json()
    streamed = events(client.post(url, json={"query": SECRET}, headers=STREAM))
    assert streamed[0]["type"] == "job"
    assert all(e["type"] == "progress" for e in streamed[1:-1])
    assert streamed[-1] == {"type": "result", "result": plain}
    assert len(plain["matches"]) == 3

    detect = f"/api/documents/{doc_id}/detect"
    body = {"categories": [], "keywords": [SECRET]}
    plain = client.post(detect, json=body).json()
    assert events(client.post(detect, json=body, headers=STREAM))[-1]["result"] == plain


def test_streamed_apply(client) -> None:
    doc_id = upload(client, corpus.many_pages(2)).json()["id"]
    hits = client.post(f"/api/documents/{doc_id}/search", json={"query": SECRET}).json()
    marks = [
        {"id": f"m{i}", "page": m["page"], "kind": "text", "rects": m["rects"]}
        for i, m in enumerate(hits["matches"])
    ]
    streamed = events(
        client.post(f"/api/documents/{doc_id}/apply", json={"marks": marks}, headers=STREAM)
    )
    phases = [e["phase"] for e in streamed if e["type"] == "progress"]
    assert phases == sorted(set(phases), key=phases.index)  # each phase is reported once in a row
    result = streamed[-1]["result"]
    assert result["verification"]["passed"] is True
    pdf = client.get(f"/api/outputs/{result['id']}/file").content
    assert SECRET not in mupdf_text(pdf)


def test_validation_errors_are_not_streamed(client) -> None:
    doc_id = upload(client, corpus.text_basic()).json()["id"]
    url = f"/api/documents/{doc_id}/search"
    assert client.post(url, json={"query": "(", "mode": "regex"}, headers=STREAM).status_code == 422
    assert client.post(url, json={"query": "x", "pages": [5]}, headers=STREAM).status_code == 404
    res = client.post(f"/api/documents/{doc_id}/detect", json={"pages": [-1]}, headers=STREAM)
    assert res.status_code == 422


def test_errors_during_the_work_are_events(client, monkeypatch) -> None:
    doc_id = upload(client, corpus.text_basic()).json()["id"]
    url = f"/api/documents/{doc_id}/apply"

    def refuse(*args, **kwargs):
        raise ValueError("Mark is off the page")

    monkeypatch.setattr(api, "redact_bytes", refuse)
    [job, error] = events(client.post(url, json={"marks": []}, headers=STREAM))
    assert job["type"] == "job"
    assert error == {"type": "error", "status": 422, "detail": "Mark is off the page"}
    assert client.post(url, json={"marks": []}).status_code == 422


def slow_pages(monkeypatch, delay: float = 0.02) -> tuple[threading.Event, list[int]]:
    """Make reading each page's text take `delay` seconds; returns (started, pages read)."""
    started = threading.Event()
    read: list[int] = []
    real = api.page_text_payload

    def slow(page):
        started.set()
        read.append(page.number)
        time.sleep(delay)
        return real(page)

    monkeypatch.setattr(api, "page_text_payload", slow)
    return started, read


def test_cancel_a_job(client, monkeypatch) -> None:
    started, read = slow_pages(monkeypatch)
    doc_id = upload(client, corpus.many_pages(100)).json()["id"]
    cancelled: list[int] = []

    def cancel_once_running() -> None:
        started.wait(5)
        time.sleep(0.3)  # long enough for a progress event
        [job_id] = list(client.app.state.jobs._jobs)
        cancelled.append(client.delete(f"/api/jobs/{job_id}").status_code)

    canceller = threading.Thread(target=cancel_once_running)
    canceller.start()
    begin = time.monotonic()
    streamed = events(
        client.post(f"/api/documents/{doc_id}/search", json={"query": "x"}, headers=STREAM)
    )
    canceller.join()
    assert time.monotonic() - begin < 1.5  # reading all 100 pages takes 2 s
    assert cancelled == [204]
    assert streamed[0]["type"] == "job"
    assert streamed[-1] == {"type": "cancelled"}
    progress = [e for e in streamed if e["type"] == "progress"]
    assert progress
    assert {(e["phase"], e["total"]) for e in progress} == {("Reading the text", 100)}
    assert 0 < len(read) < 100
    assert client.app.state.jobs._jobs == {}

    # The pages read before the cancel stay cached.
    assert len(client.app.state.store.document(doc_id).text_cache) == len(read)


def test_cancel_unknown_job(client) -> None:
    assert client.delete("/api/jobs/nope").status_code == 404


def test_disconnecting_cancels_the_job(settings, monkeypatch) -> None:
    started, read = slow_pages(monkeypatch)
    app = create_app(settings)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        headers = {"X-Session-Token": TOKEN}
        with httpx.Client(base_url=base, headers=headers, timeout=10) as http:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.05)
            data = corpus.many_pages(100)
            doc_id = http.post(
                "/api/documents",
                params={"filename": "a.pdf"},
                content=data,
                headers={"Content-Type": "application/pdf"},
            ).json()["id"]
            url = f"/api/documents/{doc_id}/search"
            with http.stream("POST", url, json={"query": "x"}, headers=STREAM) as res:
                first = json.loads(next(res.iter_lines()))
                assert first["type"] == "job"
                started.wait(5)
            # The stream is closed: the job stops and is forgotten.
            deadline = time.monotonic() + 2
            while http.delete(f"/api/jobs/{first['id']}").status_code != 404:
                assert time.monotonic() < deadline, "job still running after disconnect"
                time.sleep(0.05)
            count = len(read)
            time.sleep(0.2)
            assert len(read) == count < 100
    finally:
        server.should_exit = True
        thread.join(5)
