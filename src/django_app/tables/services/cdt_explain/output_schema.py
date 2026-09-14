"""Structured-output schema for the CDT explain call.

Passed to the LLM client as the inner ``json_schema`` object, so it must carry
``name``/``schema``/``strict`` rather than being a bare JSON Schema.

``strict`` is False: the schema is simple enough that OpenAI-compatible models
honour it either way, and litellm's translation layer for non-OpenAI providers
is best-effort. The service validates the parsed payload regardless.
"""

CDT_EXPLAIN_OUTPUT_SCHEMA: dict = {
    "name": "cdt_explanations",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "explanations": {
                "type": "array",
                "description": "One entry per block supplied, in any order.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "The block id, copied verbatim from the input.",
                        },
                        "text": {
                            "type": "string",
                            "description": "Plain-prose explanation for a non-technical reader.",
                        },
                    },
                    "required": ["id", "text"],
                },
            }
        },
        "required": ["explanations"],
    },
    "strict": False,
}
