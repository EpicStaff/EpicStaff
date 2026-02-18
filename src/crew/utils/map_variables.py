from dotdict import DotDict
import re
from loguru import logger


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

    for output_key, input_key in map.items():
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
                    if set_missing_variables:
                        # end_node behavior
                        logger.warning(
                            f"Cannot find variable `{key}` for `{input_key}`. Setted {key} = 'not found'"
                        )
                        value = "not found"
                    else:
                        raise
                except Exception as e:
                    raise Exception(e)

        if isinstance(value, DotDict):
            value = value.model_dump()
        if isinstance(value, list):
            converted_list = [
                v.model_dump() if isinstance(v, DotDict) else v for v in value
            ]
            value = converted_list

        output_dict[output_key] = value

    return output_dict
