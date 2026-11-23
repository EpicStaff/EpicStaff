"""Fixed texts sent to a client or a model in place of raw exception text.

Raw exception text may carry credentials or internal details, so it is only logged.
"""

MESSAGE_PROCESSING_FAILED = "The message couldn't be processed."
TOOL_CALL_FAILED = "The tool call failed."
KNOWLEDGE_SEARCH_FAILED = "The knowledge search failed."
