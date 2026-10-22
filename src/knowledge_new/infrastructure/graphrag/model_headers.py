from graphrag_llm.config import ModelConfig


def set_extra_headers(model_config: ModelConfig, extra_headers: dict[str, str]) -> None:
    """Send `extra_headers` with every litellm call made through `model_config`.

    graphrag_llm has no headers field on `ModelConfig`; it spreads `call_args`
    into each litellm completion/embedding call, so the headers go there.
    Leaves `model_config` unchanged when there are none.
    """
    if extra_headers:
        model_config.call_args = {**model_config.call_args, "extra_headers": dict(extra_headers)}
