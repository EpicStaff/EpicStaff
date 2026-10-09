import json
import queue
import threading
from concurrent.futures import Executor, Future
from io import BytesIO
from typing import Callable

from django.db import connection


def data_to_json_file(data, filename):
    json_bytes = json.dumps(data, indent=4).encode("utf-8")
    file_obj = BytesIO(json_bytes)
    file_obj.name = filename
    file_obj.seek(0)
    return file_obj


def run_concurrently(targets: list[Callable]) -> list:
    """Runs each callable in `targets` in its own real thread (own DB
    connection each), synchronized to start together via a Barrier to
    maximize actual lock contention, and returns the collected per-thread
    results (return value, or the raised exception) in completion order.
    """
    n = len(targets)
    results: "queue.Queue" = queue.Queue()
    barrier = threading.Barrier(n)

    def _worker(target: Callable):
        try:
            barrier.wait(timeout=10)
            results.put(target())
        except Exception as exc:  # noqa: BLE001 - surfaced to the test via queue
            results.put(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=_worker, args=(t,)) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    return [results.get(timeout=1) for _ in range(n)]


class InlineExecutor(Executor):
    """Run each submitted callable at once, on the calling thread.

    Background jobs then finish before `submit` returns, inside the test's
    database transaction, so tests stay deterministic and see their effects.
    """

    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:
            future.set_exception(error)
        return future
