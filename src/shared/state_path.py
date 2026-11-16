"""Flow state paths such as `variables.user[0].name`: how crew splits one, and which it refuses.

Crew walks the state with getattr/setattr, so a segment like `__class__` would reach the
DotDict class, which every session in a crew process shares, and `_properties` the DotDict's
internals. No segment may therefore start with `_`. Crew applies the rule at run time;
Django applies it when a flow is saved or imported, so the author hears of it earlier.

A classification table's input map path may also hold dynamic keys, such as
`messages[variables.index]`: a bracket holding a variable path whose value is the key. A bracket
holds either list index digits or one dotted path of word segments; anything else (nested
brackets, a sign, a `|`) is refused rather than read some other way. The path must start with
a name, not a bracket, so flow data never picks the root.
"""

import re

# Words or list indices like [0]. Any other character only separates segments.
_PATH_SEGMENT = re.compile(r"\w+|\[\d+\]")
_LIST_INDEX = re.compile(r"\[\d+\]")
# A bracket holding anything but list index digits: a dynamic key, or text refused below.
_DYNAMIC_KEY = re.compile(r"\[(?!\d+\])([^\[\]]+)\]")
_DYNAMIC_KEY_PATH = re.compile(r"\w+(?:\.\w+)*")


def split_state_path_segments(path: str) -> list[str]:
    """Split `path` into its segments, without checking them."""
    return _PATH_SEGMENT.findall(path)


def state_path_refusal(path: str) -> str | None:
    """Return why crew refuses `path`, worded for the flow author; None when it is allowed."""
    if any(segment.startswith("_") for segment in split_state_path_segments(path)):
        return f"Variable path '{path}' is not allowed: path segments cannot start with '_'."
    return None


def split_dynamic_key_path_fragments(path: str) -> list[str]:
    """Split `path` at its dynamic keys, without checking it.

    Returns:
        Plain fragments at even positions and the dynamic keys' own paths at odd ones:
        `a.b[c.d].e` gives `["a.b", "c.d", ".e"]`.
    """
    return _DYNAMIC_KEY.split(path)


def dynamic_key_path_refusal(path: str) -> str | None:
    """Return why crew refuses `path`, a path that may hold dynamic keys; None when allowed."""
    refusal = state_path_refusal(path)
    if refusal is not None:
        return refusal
    fragments = split_dynamic_key_path_fragments(path)
    # A leading dynamic key would let flow data name the root, such as all of `variables`.
    if not split_state_path_segments(fragments[0]):
        return (
            f"Variable path '{path}' is not allowed: it must start with a variable name, "
            "such as variables.messages[variables.index], not with a bracket."
        )
    plain_fragments = [_LIST_INDEX.sub("", fragment) for fragment in fragments[::2]]
    if any("[" in fragment or "]" in fragment for fragment in plain_fragments) or not all(
        _DYNAMIC_KEY_PATH.fullmatch(key_path) for key_path in fragments[1::2]
    ):
        return (
            f"Variable path '{path}' is not allowed: a bracket holds either a list index such "
            "as [0] or one variable path such as [variables.index], with no brackets, signs "
            "or '|' inside."
        )
    return None
