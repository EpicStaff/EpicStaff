import graphrag.api.query as _query
import graphrag.query.structured_search.basic_search.search as _basic
import graphrag.query.structured_search.drift_search.drift_context as _drift
import graphrag.query.structured_search.global_search.search as _global
import graphrag.query.structured_search.local_search.search as _local

GROUNDING_PROMPT_PATCH = """

---Data Grounding Rules---

Base your response only on the information found in the provided data tables.
Do not supplement answers with general knowledge or training data.
If the data tables do not contain information that directly answers the question,
but contain something related or partially matching, highlight what is available
and clarify how it differs from what was asked.
If the data tables contain no relevant information at all, let the user know
that the available documents do not cover this topic.

---End of Data Grounding Rules---"""

DRIFT_LENGTH_LIMIT_PROMPT_PATCH = """

---Response Length Override---

Disregard any fixed character-count requirement stated above for the intermediate_answer.
Make it as complete as the available data allows; do not truncate or pad to a fixed length.

---End of Response Length Override---"""

_is_patched = False


def patch_graphrag_prompts() -> None:
    global _is_patched
    if _is_patched:
        return
    _is_patched = True

    _basic.BASIC_SEARCH_SYSTEM_PROMPT += GROUNDING_PROMPT_PATCH
    _local.LOCAL_SEARCH_SYSTEM_PROMPT += GROUNDING_PROMPT_PATCH
    _global.MAP_SYSTEM_PROMPT += GROUNDING_PROMPT_PATCH
    _global.REDUCE_SYSTEM_PROMPT += GROUNDING_PROMPT_PATCH
    _drift.DRIFT_LOCAL_SYSTEM_PROMPT += (
        GROUNDING_PROMPT_PATCH + DRIFT_LENGTH_LIMIT_PROMPT_PATCH
    )
    _drift.DRIFT_REDUCE_PROMPT += GROUNDING_PROMPT_PATCH

    def _load_search_prompt(prompt_config: str | None) -> str | None:
        return (prompt_config + GROUNDING_PROMPT_PATCH) if prompt_config else None

    _query.load_search_prompt = _load_search_prompt
