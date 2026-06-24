from typing import Any

from langgraph.types import StreamWriter

from models.state import State
from services.graph.events import StopEvent
from services.graph.nodes import BaseNode


class ScheduleTriggerNode(BaseNode):
    TYPE = "SCHEDULE_TRIGGER"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map={},
            output_variable_path=None,
        )

    async def execute(
        self, state: State, writer: StreamWriter, execution_order: int, input_: Any
    ):
        return None

    async def run(self, state: State, writer: StreamWriter) -> State:
        try:
            execution_order = self._calc_execution_order(
                state=state, name=self.node_name
            )
            input_ = self.get_input(state=state)
            self.add_start_message(
                writer=writer, input_=input_, execution_order=execution_order
            )
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
            self.add_error_message(
                writer=writer, error=e, execution_order=execution_order
            )
            raise e
