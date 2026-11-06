import re

from services.graph.exceptions import InvalidStatePathError

# Words or list indices like [0].
_PATH_SEGMENT = re.compile(r"\w+|\[\d+\]")


def split_state_path(path: str) -> list[str]:
    """Split a flow state path such as `variables.user[0].name` into its segments.

    The state is walked with getattr/setattr, so a segment like `__class__` would reach the
    DotDict class, which every session in this crew process shares, and `_properties` the
    DotDict's internals. No segment may therefore start with `_`.

    Raises:
        InvalidStatePathError: A segment starts with `_`.
    """
    segments = _PATH_SEGMENT.findall(path)
    if any(segment.startswith("_") for segment in segments):
        raise InvalidStatePathError(
            f"Variable path '{path}' is not allowed: path segments cannot start with '_'."
        )
    return segments
