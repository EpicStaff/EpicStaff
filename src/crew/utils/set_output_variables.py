import re
from typing import Any
from loguru import logger
from dotdict import DotDict
from models.state import State

def set_output_variables(
    state: State, output_variable_path: str | None, output: Any
) -> None:
    """
    Saving output into state["variables"] in output_variable_path.
    """
    if output_variable_path is None:
        return

    variables: DotDict = state["variables"]
    pattern = re.compile(r"\w+|\[\d+\]")  # Match words or list indices like [0]

    keys: list[str] = pattern.findall(output_variable_path)
    if keys[0] != "variables":
        raise ValueError(f"`{output_variable_path}` does not contain name `variables`")
    
    keys = keys[1:]  # Remove "variables" from path
    value = variables

    if len(keys) == 0:
        if not isinstance(output, dict):
            logger.warning(f"Output `{output}` should be a dict to update the whole variables")
            return
                
        value.update(output)
        return
    
    for key in keys[:-1]:
        if key.startswith("[") and key.endswith("]"):  # List index
            index = int(key[1:-1])
            value = value[index]
        else:
            value = getattr(value, key)


    last_key_name = keys[-1]
    if last_key_name.startswith("[") and last_key_name.endswith("]"):
        index = int(last_key_name[1:-1])
        value[index] = output
    elif hasattr(value, last_key_name) and isinstance(getattr(value, last_key_name), DotDict):
        if isinstance(output, dict):
            getattr(value, last_key_name).update(output)
        else:
            setattr(value, last_key_name, output)

    else:
        setattr(value, last_key_name, output)