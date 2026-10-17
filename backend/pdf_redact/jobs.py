"""Long operations streamed to the browser with progress, and cancelled on request.

When a request asks for ``application/x-ndjson``, the operation runs in a worker thread and the
response is a stream of JSON lines:

- ``{"type": "job", "id": …}`` first, the id to cancel with ``DELETE /api/jobs/{id}``;
- ``{"type": "progress", "phase": …, "done": …, "total": …}`` while it runs (a total of 0 means
  unknown);
- then exactly one of ``{"type": "result", "result": …}`` (the usual JSON response body),
  ``{"type": "error", "status": …, "detail": …}`` or ``{"type": "cancelled"}``.

A client that goes away also cancels the operation. Without that header, the endpoint answers
with plain JSON as usual.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import TypeVar

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.types import Receive, Scope, Send

from .core.progress import Cancelled, tracking

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

NDJSON = "application/x-ndjson"
# How often progress is sent at most, in seconds.
PROGRESS_INTERVAL = 0.1


class Job:
    def __init__(self) -> None:
        self.id = uuid.uuid4().hex
        self.finished = threading.Event()
        self.outcome: dict = {}
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._progress: tuple[str, int, int] = ("", 0, 0)

    def update(self, phase: str, done: int, total: int) -> None:
        if self._cancelled.is_set():
            raise Cancelled
        with self._lock:
            self._progress = (phase, done, total)

    def progress(self) -> tuple[str, int, int]:
        with self._lock:
            return self._progress

    def cancel(self) -> None:
        self._cancelled.set()

    def run(self, work: Callable[[], BaseModel]) -> None:
        with tracking(self):
            try:
                outcome = {"type": "result", "result": jsonable_encoder(work())}
            except Cancelled:
                outcome = {"type": "cancelled"}
            except HTTPException as exc:
                outcome = {"type": "error", "status": exc.status_code, "detail": exc.detail}
            except Exception:
                log.exception("Job failed")
                outcome = {"type": "error", "status": 500, "detail": "Internal Server Error"}
        self.outcome = outcome
        self.finished.set()


class Jobs:
    """The jobs that are running, by id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def add(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def remove(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)

    def cancel(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
        job.cancel()

    def cancel_all(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel()


def _line(event: dict) -> bytes:
    return json.dumps(event, separators=(",", ":")).encode() + b"\n"


def wants_stream(request: Request) -> bool:
    return NDJSON in request.headers.get("accept", "")


def start(jobs: Jobs, work: Callable[[], BaseModel]) -> Job:
    """Run `work` in a worker thread."""
    job = Job()
    jobs.add(job)
    threading.Thread(target=job.run, args=(work,), name=f"job-{job.id}", daemon=True).start()
    return job


def events(job: Job) -> Iterator[bytes]:
    """The job's id, its progress, then its outcome, as JSON lines."""
    yield _line({"type": "job", "id": job.id})
    sent = None
    while not job.finished.wait(PROGRESS_INTERVAL):
        progress = job.progress()
        if progress != sent and progress[0]:
            phase, done, total = sent = progress
            yield _line({"type": "progress", "phase": phase, "done": done, "total": total})
    yield _line(job.outcome)


class JobResponse(StreamingResponse):
    def __init__(self, job: Job, jobs: Jobs) -> None:
        super().__init__(events(job), media_type=NDJSON, headers={"Cache-Control": "no-store"})
        self.job = job
        self.jobs = jobs

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Also reached when the client goes away mid-stream: stop the work.
            self.job.cancel()
            self.jobs.remove(self.job.id)


def respond(request: Request, jobs: Jobs, work: Callable[[], T]) -> T | StreamingResponse:
    """Run `work` and return its result, or stream progress if the client asked for that."""
    if not wants_stream(request):
        return work()
    return JobResponse(start(jobs, work), jobs)
