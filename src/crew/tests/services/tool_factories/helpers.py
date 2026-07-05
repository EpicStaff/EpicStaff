from typing import Any, Optional


def make_var(
    name: str,
    type: str = "string",
    input_type: str = "agent_input",
    required: bool = False,
    default_value: Any = None,
    description: str = "",
    properties: Optional[dict] = None,
    required_properties: Optional[list[str]] = None,
    item: Optional[dict] = None,
) -> dict:
    var = {
        "name": name,
        "type": type,
        "input_type": input_type,
        "required": required,
        "default_value": default_value,
        "description": description,
    }
    if properties is not None:
        var["properties"] = properties
    if required_properties is not None:
        var["required_properties"] = required_properties
    if item is not None:
        var["item"] = item
    return var
