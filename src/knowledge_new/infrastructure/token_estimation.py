"""Token counting and price lookup for index estimates, backed by litellm's offline data.

Nothing here calls a provider: tokenizers and the price map ship with litellm.
"""

import asyncio

import litellm
from domain.enums import EmbedderProviderEnum
from loguru import logger

# Rough characters-per-token ratio used when litellm cannot tokenize at all.
_FALLBACK_CHARS_PER_TOKEN = 4


def qualified_model_name(provider: str, model: str) -> str:
    """Return the `provider/model` name litellm uses to look up tokenizers and prices."""
    return f"{provider}/{model}"


def count_tokens(model: str, text: str) -> int:
    """Count `text` tokens for `model`, approximating when litellm cannot tokenize.

    litellm falls back to a generic tiktoken encoding for models it has no tokenizer
    for, so the count is only exact where `has_exact_tokenizer` says so.
    """
    return _count_all(model, [text])[0]


async def count_tokens_batch(model: str, texts: list[str]) -> list[int]:
    """Count each of `texts` for `model` in one worker thread, keeping the event loop free.

    litellm's counter is synchronous and CPU-bound; a failure is logged once per batch.
    """
    return await asyncio.to_thread(_count_all, model, texts)


def _count_all(model: str, texts: list[str]) -> list[int]:
    counts: list[int] = []
    failure: Exception | None = None
    for text in texts:
        try:
            counts.append(litellm.token_counter(model=model, text=text))
        except Exception as error:
            failure = failure or error
            counts.append(-(-len(text) // _FALLBACK_CHARS_PER_TOKEN))
    if failure is not None:
        logger.warning("litellm could not count tokens for '{}': {}", model, failure)
    return counts


def has_exact_tokenizer(provider: str) -> bool:
    """Whether litellm counts `provider`'s tokens with the provider's own tokenizer.

    Only OpenAI (tiktoken) qualifies. Other providers are counted with a generic
    encoding, which is close but not their real tokenizer.
    """
    return provider.lower() == EmbedderProviderEnum.OPENAI.value


def price_per_token(model: str) -> tuple[float, float] | None:
    """Return `(input, output)` USD per token from litellm's price map, or `None` if unpriced."""
    try:
        input_price, output_price = litellm.cost_per_token(
            model=model, prompt_tokens=1, completion_tokens=1
        )
    except Exception:
        return None
    return input_price, output_price
