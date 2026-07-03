from contextlib import contextmanager


@contextmanager
def handle_error(
    catch: type[Exception] | tuple[type[Exception], ...],
    raise_as: type[Exception],
    *context,
    msg="",
):
    try:
        yield
    except raise_as:
        raise
    except catch as e:
        if msg:
            context = (msg, *context)
        raise raise_as(*context) from e
