from typing import Any

from dotdict import DotDict
from loguru import logger
from services.graph.exceptions import InvalidStatePathError

from utils.state_path import split_state_path

_JSON_SCALAR_TYPES = (str, int, float, bool, type(None))

# What `walk_state_path` returns when a named segment is absent from the value it reads.
MISSING = object()


class _NotPlainDataError(Exception): ...


def _copy_plain_data(value):
    """Copy `value` as plain JSON data, converting DotDict/DotList and models on the way.

    Raises:
        _NotPlainDataError: `value` holds anything else, such as a bound method.
    """
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        return {key: _copy_plain_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_plain_data(item) for item in value]
    if isinstance(value, _JSON_SCALAR_TYPES):
        return value
    raise _NotPlainDataError


def split_default(mapped_path: str) -> tuple[str, bool, Any]:
    """Split an input map value `path|default` into the path, whether it has a default, and the default.

    The default is read up to the end of the value: `null` / `none` is None, `true` / `false`
    a bool (any letter case), digits an int, anything else the text itself.
    """
    if "|" not in mapped_path:
        return mapped_path, False, None
    path, default = mapped_path.split("|", 1)
    if default.lower() in ("null", "none"):
        return path, True, None
    if default.lower() == "true":
        return path, True, True
    if default.lower() == "false":
        return path, True, False
    if default.isdigit():
        return path, True, int(default)
    return path, True, default


def walk_state_path(value: Any, segments: list[str]) -> Any:
    """Follow the segments of a split state path from `value`, the way input maps read state.

    A word segment is read as an attribute, which a DotDict answers with its key; when it is
    absent the result is MISSING. A `[N]` segment indexes the value, and its IndexError,
    KeyError or TypeError propagates. The result is not checked; see `to_plain_data`.
    """
    for segment in segments:
        if segment.startswith("["):
            value = value[int(segment[1:-1])]
        else:
            try:
                value = getattr(value, segment)
            except AttributeError:
                return MISSING
    return value


def to_plain_data(value: Any, path: str) -> Any:
    """Return a plain JSON copy of `value`, which was read from the state at `path`.

    Raises:
        InvalidStatePathError: `value` is not plain data, such as a built-in method.
    """
    try:
        return _copy_plain_data(value)
    except _NotPlainDataError:
        # Attribute access on the resolved value finds a method of its type (DotDict, list,
        # str, ...) before any stored key of that name; the live method must not reach a
        # node, whose templates could walk from it into the process.
        raise InvalidStatePathError(
            f"Variable path '{path}' reads a built-in method instead of flow data: "
            "either the path goes past a text, number or list value, or a segment is named "
            "like a method (such as 'items' or 'update') — rename that variable."
        ) from None


def map_variables_to_input(
    variables: DotDict, map: dict, set_missing_variables: bool = False
) -> dict:
    """
    Map values from `variables` to a new dictionary using a mapping.

    This function extracts values from `variables` based on the given mapping,
    allowing for structured transformation of variable names into a dictionary.

    A path that is not found takes its `|default` (see `split_default`); without one it
    becomes None, or "not found" with `set_missing_variables`, and a warning is logged.

    Args:
        variables (DotDict): A dictionary-like object containing variables.
        map (dict): A dictionary specifying mappings, where keys represent
                    new dictionary keys, and values are dot-notated paths
                    referring to `variables`.

    Returns:
        dict: A dictionary with mapped keys and corresponding values from `variables`.

    Raises:
        InvalidStatePathError: A path has no segment (`''`, `'|null'`), a path segment
            starts with `_`, or the path resolves to something other than plain JSON data,
            such as a built-in method.

    Example:
        Given the following `variables`:
        ```
        variables = DotDict({
            "value1": 5,
            "foo": {
                "bar": {"test": [1, 2, 3]}
            }
        })
        ```

        And the following mapping:
        ```
        map = {
            "key1": "variables.value1",
            "key2": "variables.foo.bar"
        }
        ```

        The function will return:
        ```
        {
            "key1": 5,
            "key2": {"test": [1, 2, 3]}
        }
        ```
    """
    output_dict = {}

    for output_key, mapped_path in map.items():
        input_key, has_default, default_value = split_default(mapped_path)

        keys = split_state_path(input_key)
        # Checked before the default, which must not stand in for a path never written.
        if not keys:
            raise InvalidStatePathError(f"Input map entry '{output_key}' has no variable path.")
        if keys[0] != "variables":
            raise ValueError(f"`{input_key}` does not contain name `variables` for {output_key}")

        value = walk_state_path(variables, keys[1:])
        if value is MISSING:
            if has_default:
                value = default_value
            elif set_missing_variables:
                logger.warning("Cannot find variable `{}`. Set it to 'not found'.", input_key)
                value = "not found"
            else:
                logger.warning(
                    "Variable `{}` not found (output_key=`{}`). Setting to None.",
                    input_key,
                    output_key,
                )
                value = None

        output_dict[output_key] = to_plain_data(value, input_key)

    return output_dict
