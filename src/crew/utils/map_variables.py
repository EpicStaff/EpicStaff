from dotdict import DotDict
import re
from loguru import logger


def _clean_value(v):
    """Recursively convert proxy objects (DotDict, SharedVariables, etc.) to plain types."""
    if hasattr(v, "model_dump"):
        v = v.model_dump()
    if isinstance(v, dict):
        return _clean_dict(v)
    if isinstance(v, list):
        return _clean_list(v)
    return v


def _clean_dict(d: dict) -> dict:
    return {k: _clean_value(v) for k, v in d.items()}


def _clean_list(lst: list) -> list:
    return [_clean_value(v) for v in lst]


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
    pattern = re.compile(r"\w+|\[\d+\]")
    shared_pattern = re.compile(r"variables\.shared\[([^\]]+)\]\.(.+)")

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

        # Check for shared variable pattern: variables.shared[key].name
        shared_match = shared_pattern.match(input_key)

        if shared_match:
            access_key = shared_match.group(1).strip("'\"")
            variable_name = shared_match.group(2)

            # Resolve variable references in access key (e.g. variables.chat_id)
            if access_key.startswith("variables."):
                var_keys = pattern.findall(access_key)
                if var_keys and var_keys[0] == "variables":
                    resolved = variables
                    for vk in var_keys[1:]:
                        resolved = getattr(resolved, vk)
                    access_key = str(resolved)

            try:
                scope = variables.shared[access_key]
                value = getattr(scope, variable_name)
                if value is None and has_default:
                    value = default_value
                output_dict[output_key] = value
                continue
            except Exception as e:
                if has_default:
                    output_dict[output_key] = default_value
                elif set_missing_variables:
                    output_dict[output_key] = "not found"
                else:
                    raise
                continue

        # Normal variable path handling
        keys: list["str"] = pattern.findall(input_key)
        if keys[0] != "variables":
            raise ValueError(
                f"`{input_key}` does not contain name `variables` for {output_key}"
            )
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
                except Exception as e:
                    raise Exception(e)

        if hasattr(value, "model_dump"):
            value = value.model_dump()
        if isinstance(value, dict):
            value = _clean_dict(value)
        if isinstance(value, list):
            value = _clean_list(value)

        output_dict[output_key] = value

    return output_dict
