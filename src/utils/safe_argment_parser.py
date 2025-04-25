import logging

logger = logging.getLogger(__name__)
from RestrictedPython.PrintCollector import PrintCollector
from RestrictedPython.Guards import safe_builtins
from RestrictedPython.Eval import default_guarded_getitem
from RestrictedPython import compile_restricted
from config.config import ToolsConfig
import pandas as pd

integration_dict = ToolsConfig.integration_dict


def get_safe_execution_environment(integration_dict):
    """
    Prepare a safe execution environment for RestrictedPython using an integration dictionary
    populated with dynamically imported module members.
    
    Args:
        integration_dict (dict): Dictionary containing public members from dynamically imported modules.
    
    Returns:
        tuple: A tuple containing dictionaries for globals and locals for the execution environment.
    """
    safe_globals = safe_builtins.copy()
    # Update safe_globals with the contents of integration_dict
    safe_globals.update(integration_dict)

    safe_locals = {
            '_print_':   PrintCollector(),
            '_getitem_': default_guarded_getitem
    }
    return safe_globals, safe_locals


def parse_arguments(arg_str):
    max_length = 1000
    if pd.isna(arg_str):
        return [], {}
    if len(arg_str) > max_length:
        logger.error(f"Argument string exceeds maximum length of {max_length} characters.")
        raise ValueError(f"Input too long. Maximum allowed length is {max_length} characters.")

    args, kwargs = [], {}
    globals_dict, locals_dict = get_safe_execution_environment(integration_dict)

    for pair in arg_str.split(','):
        pair = pair.strip()
        if not pair:
            continue

        key_value = pair.split('=')
        if len(key_value) == 2:
            key, value = map(str.strip, key_value)
            if not key.isidentifier():
                logger.error(f"Invalid keyword '{key}'. Must be a valid identifier.")
                raise ValueError(f"Invalid keyword '{key}'. Must be a valid identifier.")
            byte_code = compile_restricted(value, '<string>', 'eval')
            try:
                kwargs[key] = eval(byte_code, globals_dict, locals_dict)
            except Exception as e:
                logger.error(f"Error evaluating expression '{value}': {e}")
                raise ValueError(f"Error evaluating expression: {e}")
        elif len(key_value) == 1:
            value = key_value[0].strip()
            byte_code = compile_restricted(value, '<string>', 'eval')
            try:
                args.append(eval(byte_code, globals_dict, locals_dict))
            except Exception as e:
                logger.error(f"Error evaluating expression '{value}': {e}")
                raise ValueError(f"Error evaluating expression: {e}")
        else:
            logger.error("Malformed argument. Use 'key=value' for kwargs.")
            raise ValueError("Malformed argument. Use 'key=value' for kwargs.")

    return args, kwargs
