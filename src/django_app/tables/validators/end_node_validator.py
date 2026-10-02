from loguru import logger

from tables.exceptions import EndNodeValidationError
from tables.models import EndNode


class EndNodeValidator:
    def validate(self, graph_id: int) -> EndNode | None:
        end_node = self._check_exists(graph_id)

        if end_node is not None:
            self._validate_output_map(end_node, graph_id)

        return end_node

    def _check_exists(self, graph_id: int) -> EndNode:
        try:
            return EndNode.objects.get(graph=graph_id)
        except EndNode.DoesNotExist:
            # TODO: revert back validation
            logger.warning(f"end_node is missing for flow id={graph_id}")
            # raise EndNodeValidationError(f"end_node is missing for flow id={graph_id}")

    def _validate_output_map(self, end_node: EndNode, graph_id: int) -> None:
        non_string_errors = []
        variables_path_errors = []

        if not isinstance(end_node.output_map, dict):
            raise EndNodeValidationError(
                f"End Node output_map param for graph {graph_id} must be dict"
            )

        for key, value in end_node.output_map.items():
            if not isinstance(value, str):
                non_string_errors.append(key)
            elif not value.startswith("variables"):
                variables_path_errors.append(key)

        error_messages = []

        if non_string_errors:
            if len(non_string_errors) == 1:
                msg = f'Value for "{non_string_errors[0]}" must be a string'
            else:
                msg = f'Values for "{", ".join(non_string_errors)}" must be strings'
            error_messages.append(msg)

        if variables_path_errors:
            if len(variables_path_errors) == 1:
                msg = f'Value for "{variables_path_errors[0]}" must start with "variables"'
            else:
                msg = f'Values for "{", ".join(variables_path_errors)}" must start with "variables"'
            error_messages.append(msg)

        if error_messages:
            raise EndNodeValidationError(
                f"End node errors graph[{graph_id}]: {'; '.join(error_messages)}"
            )
