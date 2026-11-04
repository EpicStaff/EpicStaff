"""Shared fakes.

Every fake here subclasses the real abstract port it replaces, so a change to a port
breaks the fake at import time rather than letting the two drift apart. ``FakeProcess``
and ``FakeClock`` are the exceptions -- there is no port behind a subprocess, and a clock
is a plain callable.
"""

from tests.fakes.admission import FakeHostMetrics
from tests.fakes.clock import FakeClock
from tests.fakes.isolation import FakeIsolationProbe
from tests.fakes.process import FakeProcess
from tests.fakes.repositories import FakeVenvRepository
from tests.fakes.transport import (
    FakeJobDispatcher,
    FakeJobFailureSink,
    FakeJobSource,
    FakeResultPublisher,
    FakeResultSink,
)
from tests.fakes.unit_of_work import FakeUnitOfWork
from tests.fakes.uv_provider import FakeUVProvider

__all__ = [
    "FakeClock",
    "FakeHostMetrics",
    "FakeIsolationProbe",
    "FakeJobDispatcher",
    "FakeJobFailureSink",
    "FakeJobSource",
    "FakeProcess",
    "FakeResultPublisher",
    "FakeResultSink",
    "FakeUVProvider",
    "FakeUnitOfWork",
    "FakeVenvRepository",
]
