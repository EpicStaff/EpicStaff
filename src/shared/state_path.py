"""Flow state paths such as `variables.user[0].name`: how crew splits one, and which it refuses.

Crew walks the state with getattr/setattr, so a segment like `__class__` would reach the
DotDict class, which every session in a crew process shares, and `_properties` the DotDict's
internals. No segment may therefore start with `_`. Crew applies the rule at run time;
Django applies it when a flow is saved or imported, so the author hears of it earlier.
"""

import re

# Words or list indices like [0]. Any other character only separates segments.
_PATH_SEGMENT = re.compile(r"\w+|\[\d+\]")


def split_state_path_segments(path: str) -> list[str]:
    """Split `path` into its segments, without checking them."""
    return _PATH_SEGMENT.findall(path)


def state_path_refusal(path: str) -> str | None:
    """Return why crew refuses `path`, worded for the flow author; None when it is allowed."""
    if any(segment.startswith("_") for segment in split_state_path_segments(path)):
        return f"Variable path '{path}' is not allowed: path segments cannot start with '_'."
    return None
