from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from utils.psutil_wrapper import psutil_wrapper
from services.graph.custom_message_writer import CustomSessionMessageWriter
from models.graph_models import *
from models.state import *
from langgraph.types import StreamWriter
from dotdict import DotDict, Expression
from utils import map_variables_to_input
from utils import set_output_variables


class BaseNode(ABC):
    TYPE = "BASE"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        input_map: dict | None = None,
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
        state_history = state.get("state_history", None)
        if not state_history:
            return 0
        return sum(1 for item in state.get("state_history") if item["name"] == name)

    def add_start_message(
        self, writer: StreamWriter, input_: Any, execution_order: int
    ):
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
        )

    def add_finish_message(
        self,
        writer: StreamWriter,
        output: Any,
        execution_order: int,
        state: State,
        **kwargs
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
            **kwargs
        )

    def add_error_message(
        self, writer: StreamWriter, error: Exception, execution_order: int
    ):
        """
        Add an error message to the graph.

        Args:
            writer (StreamWriter): A stream writer to write the message to.
            error (Exception): The exception that was raised.
            execution_order (int): The order of execution of the node.

        This function creates an error message containing details about the
        exception that occurred. It includes the session ID, node name, execution
        order, and a timestamp. The message is then written using the provided
        stream writer.
        """
        self.custom_session_message_writer.add_error_message(
            session_id=self.session_id,
            node_name=self.node_name,
            writer=writer,
            error=error,
            execution_order=execution_order,
        )

    @abstractmethod
    async def execute(
        self, state: State, writer: StreamWriter, execution_order: int, input_: Any
    ): ...

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
            Exception: If there was an exception during the execution of the node.
        """
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

            set_output_variables(
                state=state,
                output_variable_path=self.output_variable_path,
                output=output,
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

    def get_input(self, state: State):
        """
        Maps input variables from state["variables"] based on self.input_map
        and returns the mapped input.
        """

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

        variables = state["variables"]
        state_history = state["state_history"]
        state_history.append(
            {
                "type": type,
                "name": name,
                "additional_data": copy.deepcopy(kwargs),
                "input": copy.deepcopy(input),
                "variables": copy.deepcopy(variables.model_dump()),
                "output": copy.deepcopy(output),
            }
        )
