"""Progress reporting and cancellation for long engine operations.

The web layer runs an operation inside ``tracking(tracker)``. Engine loops call ``report`` with
what they are doing and how far they got; the tracker records it and raises ``Cancelled`` once the
operation has been cancelled, which unwinds the work at the next report. Outside ``tracking``,
``report`` does nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol


class Cancelled(Exception):
    """The operation was cancelled."""


class Tracker(Protocol):
    def update(self, phase: str, done: int, total: int) -> None:
        """Record progress; raise ``Cancelled`` to stop the operation."""


_tracker: ContextVar[Tracker | None] = ContextVar("tracker", default=None)


def report(phase: str, done: int = 0, total: int = 0) -> None:
    """`done` of `total` steps of `phase` are finished (a total of 0 means unknown)."""
    tracker = _tracker.get()
    if tracker is not None:
        tracker.update(phase, done, total)


@contextmanager
def tracking(tracker: Tracker) -> Iterator[None]:
    token = _tracker.set(tracker)
    try:
        yield
    finally:
        _tracker.reset(token)
