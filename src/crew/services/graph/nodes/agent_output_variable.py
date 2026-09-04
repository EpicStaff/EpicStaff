from typing import Any


def agent_output_variable_value(output: Any) -> Any:
    """Value stored at ``output_variable_path`` for TaskNode/AgentNode.

    Prefers the validated ``structured_output`` object produced by an
    ``output_schema`` enforcement; falls back to the plain ``message`` text
    when no schema was declared (``structured_output`` is ``None``).
    """
    if not isinstance(output, dict):
        return output

    structured_output = output.get("structured_output")
    if structured_output is not None:
        return structured_output

    return output.get("message")
