from loguru import logger
from utils.graph_utils import flow_location, join_with_and

from tables.constants.variables_constants import DOMAIN_VARIABLES_KEY
from tables.exceptions import EndNodeValidationError
from tables.models import EndNode


class EndNodeValidator:
    def find(self, graph_id: int, *, node_ids: set[int] | None = None) -> EndNode | None:
        """Return the flow's End node, or None when it has none.

        Args:
            node_ids: Return it only if it is one of these, such as the nodes a run
                reaches; no query is made when the set is empty. None looks at every node.
        """
        if node_ids is not None and not node_ids:
            return None
        end_nodes = EndNode.objects.filter(graph=graph_id)
        if node_ids is not None:
            end_nodes = end_nodes.filter(pk__in=node_ids)
        try:
            return end_nodes.get()
        except EndNode.DoesNotExist:
            # Allowed: a flow doesn't need an End node to run.
            logger.warning("No End node to run in flow id={}", graph_id)
            return None

    def validate(self, end_node: EndNode, *, flow_name: str | None = None) -> None:
        """Refuse the run when an output of the End node doesn't point to a flow variable.

        Args:
            flow_name: The subflow's name, named in the message; None for the flow that was run.

        Raises:
            EndNodeValidationError: An output doesn't point to a flow variable.
        """
        location = flow_location(flow_name)
        if not isinstance(end_node.output_map, dict):
            problem = (
                f"The End node{location} has a broken Output Map."
                if location
                else "The End node's Output Map is broken."
            )
            raise EndNodeValidationError(f"{problem} Set it again.")

        # Sorted: a JSONB map doesn't keep the order the user entered the outputs in.
        invalid_outputs = sorted(
            output_name
            for output_name, variable_path in end_node.output_map.items()
            if not self._is_flow_variable_path(variable_path)
        )
        if not invalid_outputs:
            return

        quoted_names = join_with_and([f'"{name}"' for name in invalid_outputs])
        example = f"{DOMAIN_VARIABLES_KEY}.{invalid_outputs[0]}"
        if len(invalid_outputs) == 1:
            message = (
                f"Output {quoted_names} of the End node{location} must be a flow variable, "
                f"like {example}."
            )
        else:
            message = (
                f"Outputs {quoted_names} of the End node{location} must be flow variables, "
                f"like {example}."
            )
        raise EndNodeValidationError(message)

    @staticmethod
    def _is_flow_variable_path(variable_path) -> bool:
        return isinstance(variable_path, str) and (
            variable_path == DOMAIN_VARIABLES_KEY
            or variable_path.startswith(f"{DOMAIN_VARIABLES_KEY}.")
        )
