from services.graph.exceptions import InvalidStatePathError
from src.shared.state_path import split_state_path_segments, state_path_refusal


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
