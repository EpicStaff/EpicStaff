import graphrag.api.query as _query
import graphrag.query.structured_search.basic_search.search as _basic
import graphrag.query.structured_search.drift_search.drift_context as _drift
import graphrag.query.structured_search.global_search.search as _global
import graphrag.query.structured_search.local_search.search as _local

_GROUNDING = """

---Data Grounding Rules---

Base your response only on the information found in the provided data tables.
Do not supplement answers with general knowledge or training data.
If the data tables do not contain information that directly answers the question,
but contain something related or partially matching, highlight what is available
and clarify how it differs from what was asked.
If the data tables contain no relevant information at all, let the user know
that the available documents do not cover this topic.

---End of Data Grounding Rules---"""

# graphrag's stock drift local prompt fixes intermediate_answer at "exactly 2000
# characters", truncating content before the reduce stage aggregates it.
_DRIFT_LENGTH_OVERRIDE = """

---Response Length Override---

Disregard any fixed character-count requirement stated above for the intermediate_answer.
Make it as complete as the available data allows; do not truncate or pad to a fixed length.

---End of Response Length Override---"""

_applied = False


def apply_prompt_grounding() -> None:
    global _applied
    if _applied:
        return
    _applied = True

    _basic.BASIC_SEARCH_SYSTEM_PROMPT += _GROUNDING
    _local.LOCAL_SEARCH_SYSTEM_PROMPT += _GROUNDING
    _global.MAP_SYSTEM_PROMPT += _GROUNDING
    _global.REDUCE_SYSTEM_PROMPT += _GROUNDING
    _drift.DRIFT_LOCAL_SYSTEM_PROMPT += _GROUNDING + _DRIFT_LENGTH_OVERRIDE
    _drift.DRIFT_REDUCE_PROMPT += _GROUNDING

    def _load_search_prompt(prompt_config: str | None) -> str | None:
        return (prompt_config + _GROUNDING) if prompt_config else None

    _query.load_search_prompt = _load_search_prompt
