from graphrag.prompts.query.basic_search_system_prompt import BASIC_SEARCH_SYSTEM_PROMPT
from graphrag.prompts.query.local_search_system_prompt import LOCAL_SEARCH_SYSTEM_PROMPT
from graphrag.prompts.query.drift_search_system_prompt import (
    DRIFT_LOCAL_SYSTEM_PROMPT,
    DRIFT_REDUCE_PROMPT,
)
from graphrag.prompts.query.global_search_map_system_prompt import MAP_SYSTEM_PROMPT
from graphrag.prompts.query.global_search_reduce_system_prompt import (
    REDUCE_SYSTEM_PROMPT,
)

_DATA_GROUNDING_RULES = """

---Data Grounding Rules---

Base your response only on the information found in the provided data tables.
Do not supplement answers with general knowledge or training data.
If the data tables do not contain information that directly answers the question,
but contain something related or partially matching, highlight what is available
and clarify how it differs from what was asked.
If the data tables contain no relevant information at all, let the user know
that the available documents do not cover this topic.

---End of Data Grounding Rules---"""

_USER_PROMPT_WRAPPER = """

---Additional Instructions---

The following instructions are provided by the user and must be applied
in addition to the role, goal, and data grounding rules described above.
Do not override or ignore the data grounding rules.

{user_prompt}

---End of Additional Instructions---"""

# The vendored drift local-stage prompt hardcodes "intermediate_answer ... exactly
# 2000 characters long". That intermediate answer feeds the drift reduce stage, so a
# fixed cap would truncate information before aggregation. We override the constraint
# here instead of editing the vendored prompt.
_DRIFT_LENGTH_OVERRIDE = """

---Response Length Override---

Disregard any fixed character-count requirement stated above for the intermediate_answer
(e.g. "exactly 2000 characters long"). Instead, make the intermediate_answer as complete
as the available data allows, matching the level of detail of the community summaries.
Do not artificially truncate or pad it to a fixed length.

---End of Response Length Override---"""


def _build_prompt(
    base_prompt: str, user_prompt: str | None = None, *, extra: str = ""
) -> str:
    # Order: base role/goal → data-grounding rules → stage-specific `extra` →
    # user instructions last (recency), explicitly subordinated to grounding.
    prompt = base_prompt + _DATA_GROUNDING_RULES + extra
    if user_prompt:
        prompt += _USER_PROMPT_WRAPPER.format(user_prompt=user_prompt)
    return prompt


def build_basic_search_prompt(user_prompt: str | None = None) -> str:
    return _build_prompt(BASIC_SEARCH_SYSTEM_PROMPT, user_prompt)


def build_local_search_prompt(user_prompt: str | None = None) -> str:
    return _build_prompt(LOCAL_SEARCH_SYSTEM_PROMPT, user_prompt)


def build_drift_search_prompt(user_prompt: str | None = None) -> str:
    return _build_prompt(
        DRIFT_LOCAL_SYSTEM_PROMPT, user_prompt, extra=_DRIFT_LENGTH_OVERRIDE
    )


def build_drift_search_reduce_prompt(user_prompt: str | None = None) -> str:
    return _build_prompt(DRIFT_REDUCE_PROMPT, user_prompt)


def build_global_search_map_prompt(user_prompt: str | None = None) -> str:
    return _build_prompt(MAP_SYSTEM_PROMPT, user_prompt)


def build_global_search_reduce_prompt(
    user_prompt: str | None = None,
    knowledge_prompt: str | None = None,
) -> str:
    """Build the global-search reduce-stage system prompt.

    Both map and reduce stages stay strictly grounded in the index — general
    knowledge is never permitted. A ``knowledge_prompt``, if supplied, is applied
    as an additional user instruction under the data-grounding rules: it can shape
    the answer but cannot license general knowledge or training data.
    """
    user_instruction = (
        "\n\n".join(p for p in (user_prompt, knowledge_prompt) if p) or None
    )
    return _build_prompt(REDUCE_SYSTEM_PROMPT, user_instruction)
