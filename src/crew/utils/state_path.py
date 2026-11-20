from services.graph.exceptions import InvalidStatePathError
from src.shared.state_path import (
    dynamic_key_path_refusal,
    split_dynamic_key_path_fragments,
    split_state_path_segments,
    state_path_refusal,
)


def split_state_path(path: str) -> list[str]:
    """Split a flow state path such as `variables.user[0].name` into its segments.

    The rule and its message live in `src/shared/state_path.py`, which Django checks on save.

    Raises:
        InvalidStatePathError: A segment starts with `_`.
    """
    refusal = state_path_refusal(path)
    if refusal is not None:
        raise InvalidStatePathError(refusal)
    return split_state_path_segments(path)


def split_dynamic_key_path(path: str) -> list[str]:
    """Split a path that may hold dynamic keys, such as `messages[variables.index]`.

    Returns `split_dynamic_key_path_fragments(path)` from `src/shared/state_path.py`, which
    also holds the rule Django checks on save.

    Raises:
        InvalidStatePathError: A segment starts with `_`, or a bracket holds something other
            than a list index or one variable path.
    """
    refusal = dynamic_key_path_refusal(path)
    if refusal is not None:
        raise InvalidStatePathError(refusal)
    return split_dynamic_key_path_fragments(path)
