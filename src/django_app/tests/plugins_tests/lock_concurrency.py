"""Two connections at once: one side paused inside the real code path, the other run meanwhile.

`Paused` wraps a callable: it runs it, then holds the caller's transaction open until it is
released. `run_pair` starts the paused side, starts the other side on a connection of its own,
waits until that one blocks on a lock or finishes, then lets the first go on. Postgres reports a
deadlock after `deadlock_timeout` (1 s); a lock wait that is not one ends when the paused side
lets go. Tests using it need committed data: `django_db(transaction=True)`.
"""

import threading
import time

from django.db import connection

LOCK_TIMEOUT = "15s"


class Paused:
    """Wraps a callable: runs it, then holds the caller's transaction open until `release()`."""

    def __init__(self, original):
        self.original = original
        self.reached = threading.Event()
        self._go = threading.Event()

    def __call__(self, *args, **kwargs):
        result = self.original(*args, **kwargs)
        self.reached.set()
        self._go.wait(20)
        return result

    def release(self):
        self._go.set()


class Side(threading.Thread):
    """Runs `work` on a connection of its own, with a lock timeout; keeps its result or error."""

    def __init__(self, name, work):
        super().__init__(name=name, daemon=True)
        self._work = work
        self.result = None
        self.error = None
        self.seconds = None

    def run(self):
        started = time.perf_counter()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
            self.result = self._work()
        except BaseException as error:  # noqa: BLE001 - asserted by the test
            self.error = error
        finally:
            self.seconds = time.perf_counter() - started
            connection.close()


def _blocked_or_done(other: Side) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
            "AND pid <> pg_backend_pid() AND wait_event_type = 'Lock'"
        )
        waiting = cursor.fetchone()[0]
    return waiting > 0 or not other.is_alive()


def run_pair(first: Side, second: Side, paused: Paused) -> None:
    """Run `first` until it reaches `paused`, then `second`; both must finish without an error."""
    first.start()
    assert paused.reached.wait(15), "the first side never reached its pause"
    second.start()
    deadline = time.monotonic() + 10
    while not _blocked_or_done(second) and time.monotonic() < deadline:
        time.sleep(0.05)
    paused.release()
    first.join(40)
    second.join(40)
    assert (first.error, second.error) == (None, None)
