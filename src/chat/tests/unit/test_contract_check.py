from application.orchestrators.bindings import contract_errors
from application.ports import GraphContract


def test_clean_contract():
    assert contract_errors(GraphContract(start_variables={"chat_history": [], "user_message": ""}, output_map={"reply": "variables.reply"})) == []


def test_every_error_is_named():
    errors = contract_errors(GraphContract(start_variables={"other": 1}, output_map={"answer": "x"}))
    assert errors == [
        "Start node variables must declare `chat_history`.",
        "Start node variables must declare `user_message`.",
        "End node output map must contain `reply`.",
    ]


def test_missing_nodes():
    assert contract_errors(GraphContract(start_variables=None, output_map=None)) == [
        "The flow has no start node.",
        "The flow has no end node.",
    ]
