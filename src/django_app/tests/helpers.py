import json
from concurrent.futures import Executor, Future
from io import BytesIO


def data_to_json_file(data, filename):
    json_bytes = json.dumps(data, indent=4).encode("utf-8")
    file_obj = BytesIO(json_bytes)
    file_obj.name = filename
    file_obj.seek(0)
    return file_obj


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
