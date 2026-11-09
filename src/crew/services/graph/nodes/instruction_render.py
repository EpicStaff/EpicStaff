from loguru import logger
from src.shared.flow_templates import render_template


def render_instructions(instructions: str, input_: dict) -> str:
    """Fill the instructions' placeholders from the node input; log what stays unfilled.

    Raises:
        RefusedPlaceholderError: The instructions hold a refused placeholder.
    """
    rendered = render_template(instructions, input_)
    if rendered.unrendered_reason:
        logger.warning(
            "Instructions sent as written, no placeholder filled: {}", rendered.unrendered_reason
        )
    for name in dict.fromkeys(rendered.missing):
        logger.warning("Instructions: no input value for placeholder {{{}}}; left as-is", name)
    return rendered.text
