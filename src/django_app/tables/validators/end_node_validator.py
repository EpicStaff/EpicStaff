from loguru import logger

from tables.exceptions import EndNodeValidationError
from tables.models import EndNode


class EndNodeValidator:
    def validate(self, graph_id: int, *, flow_name: str | None = None) -> EndNode | None:
        """Return the flow's End node, refusing an Output Map the run can't fill.

        `flow_name` names a subflow in the error; None for the flow the user ran.
        """
        end_node = self._check_exists(graph_id)

        if end_node is not None:
            self._validate_output_map(end_node, flow_name)

        return end_node

    def _check_exists(self, graph_id: int) -> EndNode:
        try:
            return EndNode.objects.get(graph=graph_id)
        except EndNode.DoesNotExist:
            # TODO: revert back validation
            logger.warning(f"end_node is missing for flow id={graph_id}")
            # raise EndNodeValidationError(f"end_node is missing for flow id={graph_id}")

    def _validate_output_map(self, end_node: EndNode, flow_name: str | None) -> None:
        output_map = end_node.output_map
        if not isinstance(output_map, dict) or not all(
            isinstance(value, str) for value in output_map.values()
        ):
            raise EndNodeValidationError.broken_output_map(flow_name=flow_name)

        keys_not_variables = [
            key for key, value in output_map.items() if not value.startswith("variables")
        ]
        if keys_not_variables:
            raise EndNodeValidationError.outputs_not_variables(
                keys=keys_not_variables, flow_name=flow_name
            )
