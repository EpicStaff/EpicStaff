from typing import Any, Literal, TypedDict

from dotdict import DotDict


class StateHistoryItem(TypedDict):
    type: Literal["CREW", "PYTHON", "FILE_EXTRACTOR", "LLM", "END"]
    name: str
    additional_data: dict
    variables: dict  # for output
    input: Any
    output: Any


class State(TypedDict):
    state_history: list["StateHistoryItem"]
    variables: DotDict
    system_variables: Any
    execution_counts: dict
