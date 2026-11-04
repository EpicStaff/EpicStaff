import re
from collections.abc import Iterable

from utils.graph_utils import node_label, node_list_phrase

from tables.constants.variables_constants import DOMAIN_VARIABLES_KEY
from tables.exceptions import SubGraphNodeRunValidationError
from tables.models import SubGraphNode

# The node type as the flow editor's add-node menu names it.
_SUBFLOW_LABEL = "Subflow"

# NOTE: mirrors crew's `map_variables_to_input` (src/crew/utils/map_variables.py), which
# splits a path into these tokens and fails unless the first one is `variables`; change
# both together.
_PATH_TOKEN_PATTERN = re.compile(r"\w+|\[\d+\]")
_DEFAULT_SEPARATOR = "|"


class SubGraphNodeValidator:
    """Refuses a run whose Subflow node has an input crew fails to read.

    Crew reads every input when the node starts, and fails on a value that isn't text
    or whose path doesn't start with `variables` (a `|default` suffix aside). Anything
    else it reads, at worst as None, so only those are refused. The output path isn't
    checked: crew puts `variables.` in front of any path that lacks it, so every output
    path is stored. Saving any input is allowed, so this is checked only before a run.
    """

    def validate_runnable(
        self, node_list: Iterable[SubGraphNode], *, flow_name: str | None = None
    ) -> None:
        """Refuse the run when an input doesn't point to a flow variable, naming the first one.

        Nodes are checked in the order given, inputs in the order of their names.

        Args:
            node_list: Ordered as the canvas numbers the nodes.
            flow_name: The subflow's name, named in the message; None for the flow that was run.

        Raises:
            SubGraphNodeRunValidationError: An input doesn't point to a flow variable.
        """
        for node in node_list:
            # A map that isn't a dict fails when the session data is built, before crew.
            if not isinstance(node.input_map, dict):
                continue
            # Sorted: a JSONB map doesn't keep the order the user entered the inputs in.
            for input_name in sorted(node.input_map):
                if not self._is_flow_variable_path(node.input_map[input_name]):
                    raise SubGraphNodeRunValidationError(self._message(node, input_name, flow_name))

    @staticmethod
    def _is_flow_variable_path(variable_path) -> bool:
        if not isinstance(variable_path, str):
            return False
        path = variable_path.split(_DEFAULT_SEPARATOR, 1)[0]
        tokens = _PATH_TOKEN_PATTERN.findall(path)
        return bool(tokens) and tokens[0] == DOMAIN_VARIABLES_KEY

    @staticmethod
    def _message(node: SubGraphNode, input_name: str, flow_name: str | None) -> str:
        label = node_label(node_name=node.node_name, node_number=node.node_number)
        node_phrase = node_list_phrase(_SUBFLOW_LABEL, [label], flow_name)
        return (
            f'Input "{input_name}" of {node_phrase} must be a flow variable, '
            f"like {DOMAIN_VARIABLES_KEY}.{input_name}."
        )
