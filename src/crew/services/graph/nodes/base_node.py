from abc import ABC, abstractmethod
from typing import Any, Literal, NoReturn

from langgraph.types import StreamWriter
from loguru import logger
from models.state import State
from services.graph.custom_message_writer import CustomSessionMessageWriter
from services.graph.events import StopEvent
from services.graph.exceptions import NodeExecutionError, PublicNodeError, StopSession
from src.shared.bench_log import BENCH_LEVEL
from src.shared.public_error import (
    PublicErrorMessage,
    build_public_error_message,
    new_error_correlation_id,
)
from utils import map_variables_to_input, set_output_variables
from utils.node_label import node_label_from_runtime_name


class BaseNode(ABC):
    TYPE = "BASE"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        input_map: dict | Literal["__all__"] | None = None,
        output_variable_path: str | None = None,
        custom_session_message_writer: CustomSessionMessageWriter | None = None,
    ):
        """
        Initialize a BaseNode instance.

        Args:
            session_id (int): The unique identifier for the session.
            node_name (str): The name of the node.
            input_map (dict | None, optional): A mapping of input variables. Defaults to an empty dictionary if not provided.
            output_variable_path (str | None, optional): The path to store the output variable. Defaults to None.
        """

        self.session_id = session_id
        self.node_name = node_name
        self.input_map = input_map if input_map is not None else {}
        self.output_variable_path = output_variable_path
        self.stop_event = stop_event
        self.custom_session_message_writer = CustomSessionMessageWriter() or None

    def _calc_execution_order(self, state: State, name: str) -> int:
        """
        Calculate the number of times the node with the given name has been executed.

        Args:
            state (State): The current state.
            name (str): The name of the node.

        Returns:
            int: The number of times the node has been executed.
        """
        return state.get("execution_counts", {}).get(name, 0)

    def add_start_message(self, writer: StreamWriter, input_: Any, execution_order: int):
        """
        Add a start message to the graph.

        Args:
            writer (StreamWriter): A stream writer to write the message to.
            input_ (Any): The input to the node.
            execution_order (int): The order of execution of the node.
        """
        self.custom_session_message_writer.add_start_message(
            session_id=self.session_id,
            node_name=self.node_name,
            input_=input_,
            writer=writer,
            execution_order=execution_order,
            node_type=self.TYPE,
        )

    def add_finish_message(
        self,
        writer: StreamWriter,
        output: Any,
        execution_order: int,
        state: State,
        **kwargs,
    ):
        """
        Add a finish message to the graph.

        Args:
            writer (StreamWriter): A stream writer to write the message to.
            output (Any): The output of the node.
            execution_order (int): The order of execution of the node.
            state (State): The current state of the graph.
            **kwargs: Additional data to include in the finish message.

        This function creates a finish message containing the node's output,
        current state variables, and state history. It also includes any
        additional data passed as keyword arguments. The message is then
        written using the provided stream writer.
        """
        self.custom_session_message_writer.add_finish_message(
            session_id=self.session_id,
            node_name=self.node_name,
            writer=writer,
            output=output,
            execution_order=execution_order,
            state=state,
            node_type=self.TYPE,
            **kwargs,
        )

    @property
    def node_label(self) -> str:
        """The node's label as the user sees it on the canvas, e.g. "Search docs #1"."""
        return node_label_from_runtime_name(self.node_name)

    def add_error_message(self, writer: StreamWriter, public_details: str, execution_order: int):
        """Stream an error message showing `public_details`, which must be safe to show."""
        self.custom_session_message_writer.add_error_message(
            session_id=self.session_id,
            node_name=self.node_name,
            writer=writer,
            execution_order=execution_order,
            node_type=self.TYPE,
            public_details=public_details,
        )

    def _raise_failure(
        self, writer: StreamWriter, error: Exception, execution_order: int
    ) -> NoReturn:
        """Stream the error message for `error`, then raise what the session reports.

        A `PublicNodeError` is shown as it is. Any other error may carry internal text, so it
        is logged and the user sees a generic message with a reference to the log line.
        `StopSession` is re-raised unchanged, since the session ends a stop on its own path;
        everything else is raised as a `NodeExecutionError` carrying what the user was shown.
        """
        if isinstance(error, StopSession):
            self.add_error_message(
                writer=writer, public_details=str(error), execution_order=execution_order
            )
            raise error
        if isinstance(error, PublicNodeError):
            public_message = str(error)
            correlation_id = error.correlation_id
        else:
            correlation_id = new_error_correlation_id()
            logger.opt(exception=error).error(
                "Node execution failed: {error} (correlation_id={correlation_id}, "
                "session_id={session_id}, node_name={node_name})",
                error=str(error),
                correlation_id=correlation_id,
                session_id=self.session_id,
                node_name=self.node_name,
            )
            public_message = build_public_error_message(
                PublicErrorMessage.NODE_EXECUTION_FAILED, correlation_id
            )
        self.add_error_message(
            writer=writer, public_details=public_message, execution_order=execution_order
        )
        raise NodeExecutionError(public_message, correlation_id=correlation_id) from error

    @abstractmethod
    async def execute(
        self, state: State, writer: StreamWriter, execution_order: int, input_: Any
    ): ...

    def get_output_variable_value(self, output: Any) -> Any:
        """Value stored at output_variable_path. Default: whole output."""
        return output

    async def run(self, state: State, writer: StreamWriter) -> State:
        """
        Run the node.

        This function will run the node and update the state with the output
        of the node. It will also write start and finish messages to the
        writer.

        Args:
            state (State): The current state of the session.
            writer (StreamWriter): A stream writer to write the messages to.

        Returns:
            State: The updated state.

        Raises:
            NodeExecutionError: The node failed; its error message has been streamed.
            StopSession: The session was stopped while the node ran.
        """
        execution_order = 0
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="node_start",
            session_id=self.session_id,
            node_name=self.node_name,
            node_type=type(self).__name__,
        )
        try:
            sysvars = state.get("system_variables") or {}
            execution_order = sysvars.get("execution_order", 0)
            sysvars["execution_order"] = execution_order + 1
            state["system_variables"] = sysvars
            input_ = self.get_input(state=state)
            self.add_start_message(writer=writer, input_=input_, execution_order=execution_order)
            output = await self.execute(
                state=state,
                writer=writer,
                execution_order=execution_order,
                input_=input_,
            )

            set_output_variables(
                state=state,
                output_variable_path=self.output_variable_path,
                output=self.get_output_variable_value(output),
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

            logger.log(
                BENCH_LEVEL,
                "bench {checkpoint}",
                checkpoint="node_end",
                session_id=self.session_id,
                node_name=self.node_name,
                node_type=type(self).__name__,
                ok=True,
            )
            return state

        except Exception as e:
            logger.log(
                BENCH_LEVEL,
                "bench {checkpoint}",
                checkpoint="node_end",
                session_id=self.session_id,
                node_name=self.node_name,
                node_type=type(self).__name__,
                ok=False,
            )
            self._raise_failure(writer=writer, error=e, execution_order=execution_order)

    def get_input(self, state: State):
        """
        Maps input variables from state["variables"] based on self.input_map
        and returns the mapped input.
        """
        if self.input_map == "__all__":
            return state["variables"]
        return map_variables_to_input(state["variables"], self.input_map)

    def update_state_history(
        self, state: State, type: str, name: str, input: Any, output: Any, **kwargs
    ):
        """
        Update the state history with a new entry.

        Args:
            state (State): The current state containing state history and variables.
            type (str): The type of the node (e.g., "CREW", "PYTHON").
            name (str): The name of the node.
            input (Any): The input data to the node.
            output (Any): The output data from the node.
            **kwargs: Additional data to store in the state history.

        This function appends a new entry to the state's history, capturing the
        type, name, input, output, and any additional data. It deep copies the
        input, output, and additional data to ensure that the history reflects
        the state at the time of execution.
        """

        # TODO: remove completely if nothing breaks
        # variables = state["variables"]
        # state_history = state["state_history"]
        # state_history.append(
        #     {
        #         "type": type,
        #         "name": name,
        #         "additional_data": copy.deepcopy(kwargs),
        #         "input": copy.deepcopy(input),
        #         "variables": variables.deep_dump(),
        #         "output": copy.deepcopy(output),
        #     }
        # )

        # counts = state.setdefault("execution_counts", {})
        # counts[name] = counts.get(name, 0) + 1

    async def post_init(self, *args, **kwargs): ...
