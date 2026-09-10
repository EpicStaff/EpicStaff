from contextlib import contextmanager


@contextmanager
def handle_error(
    catch: type[Exception] | tuple[type[Exception], ...],
    raise_as: type[Exception],
    *context,
    msg="",
):
    """Translate exceptions raised in the wrapped block into a domain error.

    Any exception matching `catch` raised inside the `with` block is re-raised
    as `raise_as`, built from `context` and chained to the original via
    `raise ... from`. An exception that is already an instance of `raise_as`
    propagates unchanged, so wrapping never double-translates a domain error.

    Args:
        catch: Exception type, or tuple of types, to translate.
        raise_as: Domain exception type to raise in place of a caught exception.
        *context: Positional arguments forwarded to the `raise_as` constructor.
        msg: When non-empty, inserted as the first positional argument to
            `raise_as`. Defaults to `''` (nothing prepended).

    Raises:
        raise_as: When the block raises a `catch` exception, or propagates
            `raise_as` raised inside the block unchanged.

    """
    try:
        yield
    except raise_as:
        raise
    except catch as e:
        if msg:
            context = (msg, *context)
        raise raise_as(*context) from e
