from typing import Any

from langgraph.types import StreamWriter
from loguru import logger
from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import InvalidStatePathError, NodeConfigurationError
from services.graph.nodes.base_node import BaseNode
from src.shared.models import TelegramTriggerNodeFieldData
from utils import set_output_variables


class TelegramTriggerNode(BaseNode):
    TYPE = "TELEGRAM_TRIGGER"
    LABEL = "Telegram Trigger node"

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
            try:
                output = (
                    input_.get("telegram_payload", {}).get(field.parent, {}).get(field.field_name)
                )
            # The update holds something other than an object where the field path expects one.
            except AttributeError as error:
                raise NodeConfigurationError(
                    f'{self._display_name()}: field "{field.parent}.{field.field_name}" '
                    "can't be read from the update."
                ) from error

            if output is None:
                logger.debug(
                    f"Field '{field.field_name}' not found in '{field.parent}'"
                )  # if user using 1 trigger for different telegram updates it's ok

            try:
                set_output_variables(
                    state=state,
                    output_variable_path=field.variable_path,
                    output=output,
                )
            # set_output_variables raises ValueError for a path outside `variables`.
            except ValueError as error:
                raise InvalidStatePathError(
                    f'{self._display_name()}: variable path "{field.variable_path}" '
                    "isn't a flow variable."
                ) from error
            # Raised when a segment of the path is missing or can't hold the next one.
            except (IndexError, KeyError, TypeError, AttributeError) as error:
                raise InvalidStatePathError(
                    f'{self._display_name()}: variable path "{field.variable_path}" doesn\'t exist.'
                ) from error

        return state

    async def run(self, state: State, writer: StreamWriter) -> State:
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
            self.add_error_message(writer=writer, error=e, execution_order=execution_order)
            raise
