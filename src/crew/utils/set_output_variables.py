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

    # Check for shared variable patterns
    shared_pattern_with_var = re.compile(r"variables\.shared\[([^\]]+)\]\.(.+)")
    shared_pattern_scope = re.compile(r"variables\.shared\[([^\]]+)\]$")

    shared_match = shared_pattern_with_var.match(output_variable_path)
    scope_match = shared_pattern_scope.match(output_variable_path)

    if shared_match:
        # Write single value to specific shared variable via proxy
        access_key = shared_match.group(1).strip("'\"")
        variable_name = shared_match.group(2)
        scope = variables.shared[access_key]
        setattr(scope, variable_name, output)
        logger.info(f"Set shared variable: shared[{access_key}].{variable_name}")
        return

    elif scope_match:
        # Write dict of values to shared variable scope
        access_key = scope_match.group(1).strip("'\"")
        if not isinstance(output, dict):
            raise ValueError(f"Output for shared variable scope must be a dict, got {type(output)}")
        scope = variables.shared[access_key]
        init_defaults = output.pop('init_defaults', False)
        for var_name, var_value in output.items():
            if init_defaults:
                existing = getattr(scope, var_name)
                if existing is None:
                    setattr(scope, var_name, var_value)
                    logger.info(f"Initialized shared variable: shared[{access_key}].{var_name}")
            else:
                setattr(scope, var_name, var_value)
                logger.info(f"Set shared variable: shared[{access_key}].{var_name}")
        return

    # Normal variable path handling
    pattern = re.compile(r"\w+|\[\d+\]")  # Match words or list indices like [0]

    keys: list[str] = pattern.findall(output_variable_path)
    if keys[0] != "variables":
        raise ValueError(f"`{output_variable_path}` does not contain name `variables`")

    keys = keys[1:]  # Remove "variables" from path
    value = variables

    if len(keys) == 0:
        if not isinstance(output, dict):
            logger.warning(
                f"Output `{output}` should be a dict to update the whole variables"
            )
            return

        # Handle shared variable updates in return dict: {"shared": {access_key: {var: val}}}
        if "shared" in output and isinstance(output["shared"], dict):
            shared_proxy = getattr(variables, 'shared', None)
            if shared_proxy is not None:
                for access_key, vars_dict in output["shared"].items():
                    if isinstance(vars_dict, dict):
                        scope = shared_proxy[access_key]
                        for var_name, var_value in vars_dict.items():
                            setattr(scope, var_name, var_value)
                            logger.info(f"Set shared variable: shared[{access_key}].{var_name}")
                # Remove 'shared' before updating to avoid overwriting proxy
                output_copy = {k: v for k, v in output.items() if k != "shared"}
                if output_copy:
                    # Use deep-merge for remaining keys (same logic as below)
                    for out_key, out_val in output_copy.items():
                        existing = getattr(value, out_key, None)
                        if (
                            isinstance(out_val, dict)
                            and existing is not None
                            and isinstance(existing, (dict, DotDict))
                        ):
                            existing.update(out_val)
                        else:
                            setattr(value, out_key, out_val)
                return

        # Deep-merge: for dict-type values where the existing variable is
        # also a dict/DotDict, merge keys instead of replacing the whole dict.
        # This prevents e.g. message_history={chat_A: [...]} from wiping chat_B's
        # entries when two sessions for different chats save concurrently.
        for out_key, out_val in output.items():
            existing = getattr(value, out_key, None)
            if (
                isinstance(out_val, dict)
                and existing is not None
                and isinstance(existing, (dict, DotDict))
            ):
                existing.update(out_val)
            else:
                setattr(value, out_key, out_val)
        return

    for key in keys[:-1]:
        if key.startswith("[") and key.endswith("]"):  # List index
            index = int(key[1:-1])
            value = value[index]
        else:
            if not hasattr(value, key):
                setattr(value, key, DotDict())
            value = getattr(value, key)

    last_key_name = keys[-1]
    if last_key_name.startswith("[") and last_key_name.endswith("]"):
        index = int(last_key_name[1:-1])
        value[index] = output
    elif hasattr(value, last_key_name) and isinstance(
        getattr(value, last_key_name), DotDict
    ):
        if isinstance(output, dict):
            getattr(value, last_key_name).update(output)
        else:
            setattr(value, last_key_name, output)

    else:
        setattr(value, last_key_name, output)
