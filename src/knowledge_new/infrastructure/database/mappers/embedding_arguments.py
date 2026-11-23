def embedding_call_arguments(parameters: dict) -> dict:
    """Return an embedding config's stored settings as LiteLLM arguments.

    A null setting is "not set" and is left out, so the provider keeps its own default.
    `task_type` is stored lowercase, as the model catalog offers it, but LiteLLM sends it
    to Gemini unchanged and Gemini's TaskType values are uppercase (`RETRIEVAL_DOCUMENT`).
    """
    arguments = {name: value for name, value in parameters.items() if value is not None}
    if "task_type" in arguments:
        arguments["task_type"] = arguments["task_type"].upper()
    return arguments
