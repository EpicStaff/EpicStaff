import re
from typing import Any

from langgraph.types import StreamWriter
from loguru import logger
from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import TelegramFieldError
from services.graph.nodes.base_node import BaseNode
from src.shared.models import TelegramTriggerNodeFieldData
from utils import set_output_variables


class TelegramTriggerNode(BaseNode):
    TYPE = "TELEGRAM_TRIGGER"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        field_list: list[TelegramTriggerNodeFieldData],
    ):
        self.field_list = field_list
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map={"telegram_payload": "variables.telegram_payload"},
            output_variable_path="variables",
        )

    async def execute(self, state: State, writer: StreamWriter, execution_order: int, input_: Any):
        for field in self.field_list:
            # You wonder why set_output_variables is used here?
            # By design it used only at the end of node.
            # But this node is should map multiple outputs to state variables.
            # So we reuse it here to avoid code duplication.
            # I don't like it too, but whatever.
            # A missing field is None, but a part of the path that holds something other
            # than an object fails.
            try:
                output = (
                    input_.get("telegram_payload", {}).get(field.parent, {}).get(field.field_name)
                )
            except AttributeError as error:
                raise TelegramFieldError(
                    f'Telegram Trigger node "{self.node_label}": field '
                    f'"{field.parent}.{field.field_name}" can\'t be read from the update. '
                    "Check the field path."
                ) from error

            # One trigger may receive different kinds of update, so a missing field is fine.
            if output is None:
                logger.debug("Field '{}' not found in '{}'", field.field_name, field.parent)

            try:
                set_output_variables(
                    state=state,
                    output_variable_path=field.variable_path,
                    output=output,
                )
            except (IndexError, KeyError, TypeError, AttributeError, ValueError) as error:
                raise self._variable_path_error(field.variable_path, error) from error

        return state

    def _variable_path_error(self, variable_path: str, error: Exception) -> TelegramFieldError:
        """Return the error for a field's value that couldn't be stored at `variable_path`.

        A path that doesn't start with `variables`, or names nothing at all, isn't a flow
        variable. A flow variable path fails when a part of it is missing or isn't an
        object or a list.
        """
        names = re.findall(r"[A-Za-z_]\w*", variable_path)
        if isinstance(error, ValueError) or not names:
            # Suggested under the path's last name, like the user's own variable.
            variable_name = names[-1] if names else "value"
            return TelegramFieldError(
                f'Telegram Trigger node "{self.node_label}": variable path "{variable_path}" '
                f"must be a flow variable, like variables.{variable_name}."
            )
        return TelegramFieldError(
            f'Telegram Trigger node "{self.node_label}": variable path "{variable_path}" '
            "doesn't exist. Check the variable path."
        )

    async def run(self, state: State, writer: StreamWriter) -> State:
        execution_order = 0
        try:
            execution_order = self._calc_execution_order(state=state, name=self.node_name)
            input_ = self.get_input(state=state)
            self.add_start_message(writer=writer, input_=input_, execution_order=execution_order)
            output = await self.execute(
                state=state,
                writer=writer,
                execution_order=execution_order,
                input_=input_,
            )

            self.update_state_history(
                state=state,
                type=self.TYPE,
                name=self.node_name,
                input=input_,
                output=output,
            )
            self.add_finish_message(
                writer=writer,
                output=output,
                execution_order=execution_order,
                state=state,
            )

            return state

        except Exception as e:
            self._raise_failure(writer=writer, error=e, execution_order=execution_order)
