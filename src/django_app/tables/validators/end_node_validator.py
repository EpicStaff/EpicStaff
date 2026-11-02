from loguru import logger
from utils.graph_utils import flow_location, join_with_and

from tables.constants.variables_constants import DOMAIN_VARIABLES_KEY
from tables.exceptions import EndNodeValidationError
from tables.models import EndNode


class EndNodeValidator:
    def validate(self, graph_id: int, *, flow_name: str | None = None) -> EndNode | None:
        """Return the flow's End node after checking its outputs, or None when it has none.

        Args:
            flow_name: The subflow's name, named in the message; None for the flow that was run.

        Raises:
            EndNodeValidationError: An output doesn't point to a flow variable.
        """
        end_node = self._check_exists(graph_id)

        if end_node is not None:
            self._validate_output_map(end_node, flow_name=flow_name)

        return end_node

    def _check_exists(self, graph_id: int) -> EndNode | None:
        try:
            return EndNode.objects.get(graph=graph_id)
        except EndNode.DoesNotExist:
            # Allowed: a flow doesn't need an End node to run.
            logger.warning(f"end_node is missing for flow id={graph_id}")

    def _validate_output_map(self, end_node: EndNode, *, flow_name: str | None) -> None:
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
