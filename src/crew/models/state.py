from typing import Any, Literal, TypedDict
from dotdict import DotDict


class ReturnCodeError(Exception): ...


class StateHistoryItem(TypedDict):
    type: Literal["CREW", "PYTHON", "FILE_EXTRACTOR", "CONDITIONAL_EDGE", "LLM", "END"]
    name: str
    additional_data: dict
    variables: dict  # for output
    input: Any
    output: Any


class State(TypedDict):
    state_history: list["StateHistoryItem"] = []
    variables: DotDict
    system_variables: Any
    execution_counts: dict
