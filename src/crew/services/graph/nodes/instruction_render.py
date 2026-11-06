from loguru import logger
from utils.template_render import render_template


def render_instructions(instructions: str, input_: dict) -> str:
    rendered = render_template(instructions, input_)
    if rendered.unrendered_reason:
        logger.warning(
            "Instructions sent as written, no placeholder filled: {}", rendered.unrendered_reason
        )
    for name in dict.fromkeys(rendered.missing):
        logger.warning("Instructions: no input value for placeholder {{{}}}; left as-is", name)
    return rendered.text
