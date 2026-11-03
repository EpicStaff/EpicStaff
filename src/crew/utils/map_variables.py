from dotdict import DotDict
from loguru import logger
from services.graph.exceptions import InvalidStatePathError

from utils.state_path import split_state_path

_JSON_SCALAR_TYPES = (str, int, float, bool, type(None))


class _NotPlainDataError(Exception): ...


def _to_plain_data(value):
    """Copy `value` as plain JSON data, converting DotDict/DotList and models on the way.

    Raises:
        _NotPlainDataError: `value` holds anything else, such as a bound method.
    """
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        return {key: _to_plain_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_plain_data(item) for item in value]
    if isinstance(value, _JSON_SCALAR_TYPES):
        return value
    raise _NotPlainDataError


def map_variables_to_input(
    variables: DotDict, map: dict, set_missing_variables: bool = False
) -> dict:
    """
    Map values from `variables` to a new dictionary using a mapping.

    This function extracts values from `variables` based on the given mapping,
    allowing for structured transformation of variable names into a dictionary.

    Args:
        variables (DotDict): A dictionary-like object containing variables.
        map (dict): A dictionary specifying mappings, where keys represent
                    new dictionary keys, and values are dot-notated paths
                    referring to `variables`.

    Returns:
        dict: A dictionary with mapped keys and corresponding values from `variables`.

    Raises:
        InvalidStatePathError: A path segment starts with `_`, or the path resolves to
            something other than plain JSON data, such as a built-in method.

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

    for output_key, input_key in map.items():
        # Check for default value using pipe syntax: path|default
        default_value = None
        has_default = False
        if "|" in input_key:
            parts = input_key.split("|", 1)
            input_key = parts[0]
            default_value = parts[1]
            has_default = True
            if default_value.lower() in ("null", "none"):
                default_value = None
            elif default_value.lower() == "true":
                default_value = True
            elif default_value.lower() == "false":
                default_value = False
            elif default_value.isdigit():
                default_value = int(default_value)

        keys = split_state_path(input_key)
        if keys[0] != "variables":
            raise ValueError(f"`{input_key}` does not contain name `variables` for {output_key}")
        keys = keys[1:]

        value = variables
        for key in keys:
            if key.startswith("[") and key.endswith("]"):  # Handle list indices
                index = int(key[1:-1])
                value = value[index]
            else:
                try:
                    value = getattr(value, key)
                except AttributeError:
                    if has_default:
                        value = default_value
                        break
                    elif set_missing_variables:
                        logger.warning(
                            f"Cannot find variable `{key}` for `{input_key}`. Setted {key} = 'not found'"
                        )
                        value = "not found"
                    else:
                        logger.warning(
                            f"Variable `{key}` not found for `{input_key}` (output_key=`{output_key}`). Setting to None."
                        )
                        value = None
                        break

        try:
            output_dict[output_key] = _to_plain_data(value)
        except _NotPlainDataError:
            # Attribute access on the resolved value finds a method of its type (DotDict, list,
            # str, ...) before any stored key of that name; the live method must not reach a
            # node, whose templates could walk from it into the process.
            raise InvalidStatePathError(
                f"Variable path '{input_key}' reads a built-in method instead of flow data: "
                "either the path goes past a text, number or list value, or a segment is named "
                "like a method (such as 'items' or 'update') — rename that variable."
            ) from None

    return output_dict
