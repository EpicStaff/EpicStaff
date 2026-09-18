from loguru import logger


class _SafeFormatDict(dict):
    def __missing__(self, key):
        logger.warning(
            f"Instructions: no input value for placeholder {{{key}}}; left as-is"
        )
        return "{" + key + "}"


def render_instructions(instructions: str, input_: dict) -> str:
    try:
        return instructions.format_map(_SafeFormatDict(input_))
    except (ValueError, IndexError):
        # malformed/positional braces — send verbatim
        return instructions
