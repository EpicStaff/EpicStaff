"""EST-3707 Gap 1 — ReAct control-marker escaping.

Untrusted text (RAG knowledge chunks, tool output) is concatenated verbatim
into the LLM prompt in several places. If that text happens to contain a
substring shaped exactly like a ReAct control marker (``Action:``,
``Action Input:``, ``Final Answer:``, ``Observation:``), the vendored
CrewAI parser can't tell it apart from a real one — a forged marker inside
retrieved content could hijack the agent loop (fake a tool call, a "Final
Answer", or a fabricated "Observation" that never happened).

``escape_react_markers`` defeats that by inserting a zero-width space
(U+200B) immediately before the colon of any such marker-shaped substring.
This is an *escape*, not a strip/redaction: the character is invisible when
rendered, so a human (or the LLM's own semantic understanding) still reads
the original word — but it breaks the vendored parser's exact regex /
literal-substring matches, because none of them tolerate a non-whitespace,
non-digit character between the marker word and its colon.

This module is EpicStaff-owned (not a vendor patch), so it can be imported
cleanly from both crew's own code and the three vendored CrewAI call sites
that splice untrusted text into the prompt.

Deliberately a top-level module (`prompt_escape.py`, not
`utils/prompt_escape.py`): `utils/__init__.py` eagerly imports
`utils.parse_llm` -> `utils.llm_wrapper` -> `from crewai import LLM`, so any
vendored CrewAI module (loaded while `crewai/__init__.py` is still
initializing) that imports anything from the `utils` *package* triggers a
circular import back into `crewai` before it has finished initializing.
Living at the top level (still resolvable because `src/crew` is on
`sys.path`, same as `services`/`models`/`callbacks`) sidesteps that without
touching `utils/__init__.py`'s existing import graph.

Keep the patterns below in sync with the vendored parser (do not edit the
vendored files themselves without a corresponding review here):
  - src/crew/libraries/crewAI/src/crewai/agents/parser.py:77
      r"Action\\s*\\d*\\s*:[\\s]*(.*?)[\\s]*Action\\s*\\d*\\s*Input\\s*\\d*\\s*:[\\s]*(.*)"
  - src/crew/libraries/crewAI/src/crewai/agents/parser.py:99
      bare r"Action\\s*\\d*\\s*:"
  - src/crew/libraries/crewAI/src/crewai/agents/parser.py:105
      bare r"[\\s]*Action\\s*\\d*\\s*Input\\s*\\d*\\s*:"
  - src/crew/libraries/crewAI/src/crewai/agents/parser.py:8/75/96
      literal substring "Final Answer:"
  - src/crew/libraries/crewAI/src/crewai/agents/crew_agent_executor.py:241,
    src/crew/libraries/crewAI/src/crewai/translations/en.json:8
      literal substring "Observation:"
"""

import re

# Zero-width space. Renders as nothing (no visible glyph, no layout shift),
# so escaped text is still human-readable, but it is not matched by \s in
# Python's `re` module (it's Unicode category Cf, not White_Space) and is not
# a digit — so it breaks every "\s*\d*\s*:" gap the vendored regexes rely on,
# and breaks literal "Final Answer:" / "Observation:" substring checks too.
_ZERO_WIDTH_SPACE = "​"

# Matches "Action", optionally followed by whitespace/digits, optionally
# followed by "Input" + whitespace/digits, immediately followed by ":".
# This single pattern covers all three Action-shaped marker forms the parser
# checks for (bare "Action:", bare "Action Input:", and the combined
# "Action: ... Action Input: ..." regex) because in every case the parser
# requires the colon to follow "Action" (optionally "...Input") separated
# only by whitespace/digits — inserting the zero-width space right before
# that colon defeats all three at once.
_ACTION_MARKER_RE = re.compile(r"(Action\s*\d*\s*(?:Input\s*\d*\s*)?):")


def escape_react_markers(text: str) -> str:
    """Escape literal ReAct control-marker patterns inside untrusted text.

    Deterministic, non-LLM. Inserts a zero-width space immediately before the
    colon of any substring shaped like ``Action:``, ``Action Input:``,
    ``Final Answer:``, or ``Observation:`` so it no longer matches the
    vendored parser's detection patterns, while leaving the text otherwise
    byte-for-byte identical (and visually unchanged when rendered).

    Ordinary prose is left untouched: the Action pattern only fires when a
    colon directly follows "Action" (allowing only whitespace/digits and an
    optional "Input" in between) — e.g. "Action items for this week: buy
    milk" does not match, because "items" sits between "Action" and the
    colon.

    Args:
        text: Untrusted text about to be concatenated into an LLM prompt
            (a knowledge chunk, tool output, etc).

    Returns:
        The same text with any marker-shaped substrings escaped. Returns the
        input unchanged if it isn't a non-empty string (defensive: some
        call sites pass through values that are not guaranteed to be `str`,
        e.g. `ToolResult.result: Any`).
    """
    if not isinstance(text, str) or not text:
        return text

    escaped = _ACTION_MARKER_RE.sub(
        lambda match: f"{match.group(1)}{_ZERO_WIDTH_SPACE}:", text
    )
    escaped = escaped.replace("Final Answer:", f"Final Answer{_ZERO_WIDTH_SPACE}:")
    escaped = escaped.replace("Observation:", f"Observation{_ZERO_WIDTH_SPACE}:")
    return escaped
