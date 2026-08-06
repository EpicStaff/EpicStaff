"""Post-generation groundedness guard for GraphRAG search.

`apply_grounding_guard` is the only entry point: it collapses empty answers, the
library's canned no-data answer, and answers a strict LLM judge finds unsupported by the
retrieved context to an empty string, so fabricated content never reaches the agent.
"""

import logging

import pandas as pd
from enums import GraphSearchMethodEnum
from graphrag.config.models.graph_rag_config import GraphRagConfig
from graphrag.prompts.query.global_search_reduce_system_prompt import NO_DATA_ANSWER
from graphrag_llm.completion import create_completion

logger = logging.getLogger(__name__)

# Uniform across all methods; not per-request tunable. Flip here to disable.
ENFORCE_GROUNDING = True

_GROUNDED = "GROUNDED"
_NOT_GROUNDED = "NOT_GROUNDED"

_VERIFIER_PROMPT = """You are a strict grounding verifier for a knowledge-base assistant.

You are given a user QUESTION, the CONTEXT retrieved from the knowledge base, and a
draft ANSWER generated from that context. Decide whether every substantive factual
claim in the ANSWER is directly supported by the CONTEXT.

Rules:
- Judge ONLY against the CONTEXT. Your own world/training knowledge is irrelevant and
  must never be used to "fill in" or excuse a claim.
- If the ANSWER introduces any fact, name, number, date, definition, specification or
  claim that is not present in (or directly inferable from) the CONTEXT, it is {not_grounded}.
- Only the CONTEXT can support a claim. A fact that appears in the QUESTION but not in
  the CONTEXT is NOT supported: if the ANSWER echoes or confirms such a fact (e.g. a date
  or name taken from the question), that makes it {not_grounded}.
- If the ANSWER merely states that the documents/knowledge base do not cover the
  question (a refusal), treat it as {grounded}. But a refusal that still asserts an
  unsupported fact (e.g. "not X, but actually Y" where Y is not in the CONTEXT) is
  {not_grounded}.
- If the CONTEXT is empty or unrelated to the ANSWER's claims, it is {not_grounded}.

Respond with a SINGLE token on the first line: {grounded} or {not_grounded}.

QUESTION:
{question}

CONTEXT:
{context}

ANSWER:
{answer}
"""


def is_no_data_answer(response) -> bool:
    """True for global search's canned no-data answer, which else reaches the agent as a
    similarity-1.0 chunk and provokes invention."""
    return bool(response) and str(response).strip() == NO_DATA_ANSWER.strip()


def _serialize_context(context_data) -> str:
    """Flatten the heterogeneous graphrag context into text for the judge.

    Passed whole: the context is already bounded to the model window upstream, so
    re-truncating here could drop the very records that support the answer and cause a
    false rejection.
    """
    if not context_data:
        return ""
    if isinstance(context_data, dict):
        items = list(context_data.items())
    elif isinstance(context_data, (list, tuple)):
        items = list(enumerate(context_data))
    else:
        return str(context_data)

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

    return "\n\n".join(parts)


async def _answer_is_grounded(
    query: str, answer: str, context, config: GraphRagConfig
) -> bool:
    """Ask the LLM judge whether `answer` is supported by `context`.

    Fails open (True) only on a judge infrastructure error, so a broken judge does not
    turn the whole knowledge base into blanket refusals.
    """
    context_text = _serialize_context(context)
    if not context_text:
        return False

    model = create_completion(
        config.get_completion_model_config(config.local_search.completion_model_id)
    )
    prompt = _VERIFIER_PROMPT.format(
        grounded=_GROUNDED,
        not_grounded=_NOT_GROUNDED,
        question=query,
        context=context_text,
        answer=answer,
    )
    try:
        response = await model.completion_async(messages=prompt, stream=False)
    except Exception:
        logger.exception("Grounding verification failed; allowing answer through")
        return True

    verdict = (response.content or "").strip().upper()
    if _NOT_GROUNDED in verdict:
        return False
    if _GROUNDED in verdict:
        return True
    # Unparseable verdict → refuse rather than pass possibly-fabricated content.
    logger.warning("Grounding verifier returned an unparseable verdict: %r", verdict)
    return False


async def apply_grounding_guard(
    query: str,
    response,
    context,
    config: GraphRagConfig,
    method: GraphSearchMethodEnum,
) -> str:
    """Return `response` if backed by `context`, else '' (empty/no-data/ungrounded)."""
    if not response or is_no_data_answer(response):
        return ""
    if not ENFORCE_GROUNDING:
        return response

    if not await _answer_is_grounded(query, str(response), context, config):
        logger.warning(
            "Grounding guard rejected %s answer for query: [%s]", method, query
        )
        return ""
    return response
