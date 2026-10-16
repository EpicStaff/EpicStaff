import pytest
from application.orchestrators.bindings import contract_errors, contract_missing
from application.ports import GraphContract

CHAT_START = {"chat_history": [], "user_message": ""}
CHAT_END = {"reply": "variables.reply"}
NO_START = "The flow has no start node."
NO_END = "The flow has no end node."
DECLARE_HISTORY = "Start node variables must declare `chat_history`."
DECLARE_MESSAGE = "Start node variables must declare `user_message`."
ADD_REPLY = "End node output map must contain `reply`."


@pytest.mark.parametrize(
    "start_variables, output_map, missing, errors",
    [
        pytest.param(
            CHAT_START, CHAT_END,
            {"missing_start_node": False, "missing_end_node": False, "start_variables": [], "end_outputs": []},
            [],
            id="passes",
        ),
        pytest.param(
            {"other": 1}, {"answer": "x"},
            {"missing_start_node": False, "missing_end_node": False, "start_variables": ["chat_history", "user_message"], "end_outputs": ["reply"]},
            [DECLARE_HISTORY, DECLARE_MESSAGE, ADD_REPLY],
            id="every-name-missing",
        ),
        pytest.param(
            None, None,
            {"missing_start_node": True, "missing_end_node": True, "start_variables": [], "end_outputs": []},
            [NO_START, NO_END],
            id="both-nodes-missing",
        ),
        pytest.param(
            None, CHAT_END,
            {"missing_start_node": True, "missing_end_node": False, "start_variables": [], "end_outputs": []},
            [NO_START],
            id="no-start-node",
        ),
        pytest.param(
            {"user_message": ""}, None,
            {"missing_start_node": False, "missing_end_node": True, "start_variables": ["chat_history"], "end_outputs": []},
            [DECLARE_HISTORY, NO_END],
            id="no-end-node-and-a-start-variable-missing",
        ),
        pytest.param(
            {"chat_history": []}, CHAT_END,
            {"missing_start_node": False, "missing_end_node": False, "start_variables": ["user_message"], "end_outputs": []},
            [DECLARE_MESSAGE],
            id="one-start-variable-missing",
        ),
        pytest.param(
            CHAT_START, {},
            {"missing_start_node": False, "missing_end_node": False, "start_variables": [], "end_outputs": ["reply"]},
            [ADD_REPLY],
            id="only-reply-missing",
        ),
    ],
)
def test_contract_names_what_is_missing_and_says_it(start_variables, output_map, missing, errors):
    found = contract_missing(GraphContract(start_variables=start_variables, output_map=output_map))
    assert found == missing
    assert contract_errors(found) == errors
