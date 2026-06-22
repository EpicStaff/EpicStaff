from crewai import LLM


# TODO: This is temporary workaround, until we can add robust way to filter out unsupported params per model in crewai
_NO_TEMPERATURE_PATTERNS = (
    "claude-opus-4",
    "claude-sonnet-4",
    "claude-haiku-4",
    "gpt-5",
    "o1",
    "o3",
    "o4",
)
_NO_STOP_PATTERNS = (
    "o1",
    "o3",
    "o4-mini",
    "o4",
)
_NO_PREFILL_PATTERNS = (
    "claude-opus-4",
    "claude-sonnet-4",
    "claude-haiku-4",
)


def _model_drops_temperature(model: str | None) -> bool:
    model = (model or "").lower()
    return any(p in model for p in _NO_TEMPERATURE_PATTERNS)


def _model_drops_stop(model: str | None) -> bool:
    model = (model or "").lower()
    return any(p in model for p in _NO_STOP_PATTERNS)


def _model_drops_prefill(model: str | None) -> bool:
    model = (model or "").lower()
    return any(p in model for p in _NO_PREFILL_PATTERNS)


def _strip_trailing_assistant(messages: list) -> list:
    """Convert trailing assistant message to a user turn so Claude 4.x doesn't reject it.

    Handles string content (preserved as-is) and list content (each block is extracted
    as its text value or the marker "[non-text content]" for non-text blocks; a list that
    contains no text blocks at all collapses to a single "[non-text content]" marker).
    """
    if not messages:
        raise ValueError("_strip_trailing_assistant received an empty messages list")
    if messages[-1].get("role") != "assistant":
        return messages
    msgs = list(messages)
    raw_content = msgs[-1].get("content")
    if isinstance(raw_content, list):
        if not raw_content:
            prefill = ""
        else:
            parts = []
            has_text = False
            for block in raw_content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text") or "")
                    has_text = True
                else:
                    parts.append("[non-text content]")
            if not has_text:
                prefill = "[non-text content]"
            else:
                prefill = "\n".join(parts)
    else:
        prefill = raw_content or ""
    msgs[-1] = {
        "role": "user",
        "content": (
            "Continue from where you left off and provide your response."
            + (f"\nYour partial progress so far:\n{prefill}" if prefill else "")
        ),
    }
    return msgs


class PatchedLLM(LLM):
    """crewai.LLM subclass that filters parameters unsupported by specific models."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # After super().__init__() self.model is normalized by crewai.
        if _model_drops_temperature(self.model):
            self.temperature = None
            self.top_p = None

    def call(
        self,
        messages,
        tools=None,
        callbacks=None,
        available_functions=None,
    ) -> str:
        if _model_drops_prefill(self.model) and isinstance(messages, list):
            messages = _strip_trailing_assistant(messages)
        return super().call(
            messages,
            tools=tools,
            callbacks=callbacks,
            available_functions=available_functions,
        )

    def supports_stop_words(self) -> bool:
        if _model_drops_stop(self.model):
            return False
        return super().supports_stop_words()
