from __future__ import annotations

import re

_TITLE_MAX_CHARS = 50
_MAX_TOOL_ITERATIONS = 10  # hard cap on tool-call rounds per user turn

_MD_TABLE_PATTERN = re.compile(
    r"(?:^|\n)"  # start of line
    r"\|[^\n]*\|\s*\n"  # header row with pipes
    r"\|[\s\-:|]+\|\s*\n"  # separator row like |---|---|
    r"(?:\|[^\n]*\|\s*\n?)*",  # zero or more body rows
    re.MULTILINE,
)

_CANCEL_KEY = "fa:cancel:{conv_id}"
_CANCEL_TTL_SECONDS = 300

# Shown in the Flow Assistant message bubble when a reasoning model
# (gpt-oss, o1, claude-thinking, etc.) consumes its entire token budget on
# the internal reasoning channel and produces no final-channel content.
# Italic markdown styling (leading + trailing underscores) distinguishes
# it visually from a normal assistant reply when rendered via <markdown>.
_REASONING_EMPTY_HINT = (
    "_The model finished without producing a final answer. This typically "
    "happens with reasoning models when the token budget is exhausted on "
    "internal reasoning. Try increasing `max_tokens` on this LLM config, "
    "or switch to a non-reasoning model._"
)
