"""Groundedness guard for GraphRAG search — the single home for the LLM-answer
correctness check.

Search-method agnostic: given the produced answer plus the context that was actually
retrieved, a strict LLM judge decides whether every substantive claim in the answer is
supported by that context. Answers that are empty, the library's canned "no data"
answer, or judged ungrounded are collapsed to an empty string, so the caller falls back
to the "documents do not cover this" path instead of letting fabricated content (e.g.
drift's primer/reduce stages inventing facts "from our sources") reach the agent.

`apply_grounding_guard` is the only entry point the search strategy needs; everything
else here (NO_DATA normalization, per-method context budget, the judge itself) is an
implementation detail of that one check, kept together so the strategy stays free of
correctness-checking logic.
"""

import asyncio
import logging

import pandas as pd
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag.config.models.language_model_config import LanguageModelConfig
from graphrag.language_model.manager import ModelManager
from graphrag.prompts.query.global_search_reduce_system_prompt import NO_DATA_ANSWER

logger = logging.getLogger(__name__)

# Always on, uniform across all methods: isolation must hold the same everywhere, so
# the flag is intentionally not exposed to per-request tuning. Flip here to disable.
ENFORCE_GROUNDING = True

# Token→char factor for capping the context handed to the judge. The token budget
# itself is the model-window-aware value already resolved upstream (django's
# adaptive_context_service via resolve_context_window) and carried in the config —
# we don't re-resolve the model window here.
_CHARS_PER_TOKEN = 3.5

_VERIFIER_NAME = "grounding_verifier_chat"

_GROUNDED = "GROUNDED"
_NOT_GROUNDED = "NOT_GROUNDED"

# Per-method retrieval token budget (config section, field) that sizes the context
# shown to the judge. Unknown methods fall back to the basic-search window.
_GROUNDING_BUDGET_FIELDS = {
    "drift_search": ("drift_search", "data_max_tokens"),
    "global_search": ("global_search", "data_max_tokens"),
    "local": ("local_search", "max_context_tokens"),
    "basic": ("basic_search", "max_context_tokens"),
}

_VERIFIER_PROMPT = """You are a strict grounding verifier for a knowledge-base assistant.

You are given a user QUESTION, the CONTEXT retrieved from the knowledge base, and a
draft ANSWER generated from that context. Decide whether every substantive factual
claim in the ANSWER is directly supported by the CONTEXT.

Rules:
- Judge ONLY against the CONTEXT. Your own world/training knowledge is irrelevant and
  must never be used to "fill in" or excuse a claim.
- If the ANSWER introduces any fact, name, number, date, definition, specification or
  claim that is not present in (or directly inferable from) the CONTEXT, it is {not_grounded}.
- If the ANSWER merely states that the documents/knowledge base do not cover the
  question (a refusal), treat it as {grounded}.
- If the CONTEXT is empty or unrelated to the ANSWER's claims, it is {not_grounded}.

Respond with a SINGLE token on the first line: {grounded} or {not_grounded}.

QUESTION:
{question}

CONTEXT:
{context}

ANSWER:
{answer}
"""


def is_no_data(response) -> bool:
    """True if the library returned its canned 'no relevant data' answer.

    Global search emits NO_DATA_ANSWER when every map score is 0. Left as-is it reaches
    the agent as a knowledge chunk (with similarity 1.0), which the agent treats as
    low-quality context and then 'helps' by inventing from training data. Normalizing
    it to an empty result routes the agent to its explicit 'no knowledge found' branch.
    """
    return bool(response) and str(response).strip() == NO_DATA_ANSWER.strip()


def _context_token_budget(config: GraphRagConfig, search_method: str) -> int:
    section, field = _GROUNDING_BUDGET_FIELDS.get(
        search_method, ("basic_search", "max_context_tokens")
    )
    return getattr(getattr(config, section), field, 0) or 0


def _serialize_context(context_data, max_chars: int) -> str:
    """Flatten the heterogeneous graphrag context payload into bounded text.

    `max_chars <= 0` means no cap (the context is already token-bounded upstream).
    """

    def _cap(text: str) -> str:
        return text if max_chars <= 0 else text[:max_chars]

    if not context_data:
        return ""

    if isinstance(context_data, dict):
        items = list(context_data.items())
    elif isinstance(context_data, (list, tuple)):
        items = list(enumerate(context_data))
    else:
        return _cap(str(context_data))

    parts: list[str] = []
    for key, value in items:
        if isinstance(value, pd.DataFrame):
            if value.empty:
                continue
            text = value.to_csv(index=False)
        elif isinstance(value, (list, tuple)):
            text = "\n".join(str(v) for v in value)
        else:
            text = str(value)
        parts.append(f"## {key}\n{text}")

    return _cap("\n\n".join(parts))


async def _averify(
    query: str, answer: str, context_text: str, model_settings: LanguageModelConfig
) -> bool:
    chat_model = ModelManager().get_or_create_chat_model(
        name=_VERIFIER_NAME,
        model_type=model_settings.type,
        config=model_settings,
    )

    prompt = _VERIFIER_PROMPT.format(
        grounded=_GROUNDED,
        not_grounded=_NOT_GROUNDED,
        question=query,
        context=context_text,
        answer=answer,
    )
    response = await chat_model.achat(prompt)
    verdict = (response.output.content or "").strip().upper()

    if _NOT_GROUNDED in verdict:
        return False
    if _GROUNDED in verdict:
        return True
    # Verdict returned but unparseable → treat as ungrounded (prefer refusing over
    # passing through possibly-fabricated content).
    logger.warning("Grounding verifier returned an unparseable verdict: %r", verdict)
    return False


def verify_grounded(
    query: str,
    answer: str,
    context_data,
    config: GraphRagConfig,
    context_token_budget: int,
) -> bool:
    """Return True if `answer` is supported by `context_data`, else False.

    `context_token_budget` is the active method's retrieval token budget (already
    sized to the model window upstream); it caps the context shown to the judge.

    Fails open (returns True) only on an infrastructure error in the judge call: a
    failing judge model must not turn the whole knowledge base into blanket refusals.
    """
    model_settings = config.get_language_model_config(config.local_search.chat_model_id)
    context_text = _serialize_context(
        context_data, int(context_token_budget * _CHARS_PER_TOKEN)
    )
    if not context_text:
        # Nothing was retrieved to support the answer.
        return False
    try:
        return asyncio.run(_averify(query, answer, context_text, model_settings))
    except Exception:
        logger.exception("Grounding verification failed; allowing answer through")
        return True


def apply_grounding_guard(
    query: str,
    response,
    context,
    config: GraphRagConfig,
    search_method: str,
) -> str:
    """Return the response only if it is backed by the retrieved context, else ''.

    Empty answers, the library's canned no-data answer, and answers the verifier
    rejects are all collapsed to an empty string, so the caller yields no chunks and
    treats the query as uncovered by the knowledge base.
    """
    if not response or is_no_data(response):
        return ""

    if not ENFORCE_GROUNDING:
        return response

    budget = _context_token_budget(config, search_method)
    if not verify_grounded(query, str(response), context, config, budget):
        logger.warning(
            "Grounding guard rejected %s answer as unsupported by retrieved "
            "context for query: [%s]",
            search_method,
            query,
        )
        return ""

    return response
