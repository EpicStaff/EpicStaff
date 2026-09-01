import graphrag.api.query as _query
import graphrag.query.structured_search.basic_search.search as _basic
import graphrag.query.structured_search.drift_search.drift_context as _drift
import graphrag.query.structured_search.global_search.search as _global
import graphrag.query.structured_search.local_search.search as _local

GROUNDING_PROMPT_PATCH = """

---Data Grounding Rules---

Base your response strictly and only on the information found in the provided data tables.
Do not use general knowledge or training data. Do not suggest, recommend, or reference any
external source (websites, social networks, documentation, etc.). Do not add any statement,
elaboration, or framing that is not directly present in the data tables. If the data tables
contain something only partially related, report solely what is present, without speculation.

---End of Data Grounding Rules---"""

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
    _drift.DRIFT_LOCAL_SYSTEM_PROMPT += GROUNDING_PROMPT_PATCH
    _drift.DRIFT_REDUCE_PROMPT += GROUNDING_PROMPT_PATCH

    def _load_search_prompt(prompt_config: str | None) -> str | None:
        return (prompt_config + GROUNDING_PROMPT_PATCH) if prompt_config else None

    _query.load_search_prompt = _load_search_prompt
