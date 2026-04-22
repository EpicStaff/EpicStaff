from typing import Any

from langgraph.types import StreamWriter

from src.crew.models.graph_models import (
    StartMessageData,
    GraphMessage,
    FinishMessageData,
    ErrorMessageData,
    ConditionGroupMessageData,
    ConditonGroupManipulationMessageData,
    ClassificationPromptMessageData,
)
from src.crew.models.state import State


class CustomSessionMessageWriter:
    @classmethod
    def _convert_state(cls, state: State):
        return {
            "variables": state["variables"].model_dump(),
            "state_history": state["state_history"],
        }

    @classmethod
    def add_start_message(
        cls,
        session_id: int,
        node_name: str,
        writer: StreamWriter,
        input_: Any,
        execution_order: int,
    ):
        """
        Add a start message to the graph.

        Args:
            writer (StreamWriter): A stream writer to write the message to.
            input_ (Any): The input to the node.
            execution_order (int): The order of execution of the node.
        """
        start_message_data = StartMessageData(
            input=input_,
        )
        graph_message = GraphMessage(
            session_id=session_id,
            name=node_name,
            execution_order=execution_order,
            message_data=start_message_data,
        )
        writer(graph_message)
        return graph_message

    @classmethod
    def add_finish_message(
        cls,
        session_id: int,
        node_name: str,
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

        sse_visible = kwargs.pop("sse_visible", None)
        finish_message_data = FinishMessageData(
            output=output,
            state=cls._convert_state(state=state),
            additional_data=kwargs,
            sse_visible=sse_visible,
        )
        graph_message = GraphMessage(
            session_id=session_id,
            name=node_name,
            execution_order=execution_order,
            message_data=finish_message_data,
        )
        writer(graph_message)
        return graph_message

    @classmethod
    def add_error_message(
        cls,
        session_id: int,
        node_name: str,
        writer: StreamWriter,
        error: Exception,
        execution_order: int,
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

        error_message_data = ErrorMessageData(
            details=str(error),
        )
        graph_message = GraphMessage(
            session_id=session_id,
            name=node_name,
            execution_order=execution_order,
            message_data=error_message_data,
        )
        writer(graph_message)
        return graph_message

    @classmethod
    def add_custom_message(
        cls,
        session_id: int,
        node_name: str,
        writer: StreamWriter,
        message_data: dict,
        execution_order: int,
    ):
        graph_message = GraphMessage(
            session_id=session_id,
            name=node_name,
            execution_order=execution_order,
            message_data=message_data,
        )
        writer(graph_message)
        return graph_message

    @classmethod
    def add_condition_group_message(
        cls,
        session_id: int,
        node_name: str,
        group_name: str,
        result: bool,
        writer: StreamWriter,
        execution_order: int,
        expression: str | None = None,
    ):
        condition_message_data = ConditionGroupMessageData(
            group_name=group_name,
            result=result,
            expression=expression,
        )
        graph_message = GraphMessage(
            session_id=session_id,
            name=node_name,
            execution_order=execution_order,
            message_data=condition_message_data,
        )
        writer(graph_message)
        return graph_message

    @classmethod
    def add_condition_group_manipulation_message(
        cls,
        session_id: int,
        node_name: str,
        group_name: str,
        state: dict,
        writer: StreamWriter,
        execution_order: int,
        changed_variables: dict | None = None,
    ):
        manipulation_message_data = ConditonGroupManipulationMessageData(
            group_name=group_name,
            state=cls._convert_state(state=state),
            changed_variables=changed_variables or {},
        )
        graph_message = GraphMessage(
            session_id=session_id,
            name=node_name,
            execution_order=execution_order,
            message_data=manipulation_message_data,
        )
        writer(graph_message)
        return graph_message

    @classmethod
    def add_classification_prompt_message(
        cls,
        session_id: int,
        node_name: str,
        writer: StreamWriter,
        execution_order: int,
        prompt_id: str,
        prompt_text: str,
        raw_response: str,
        parsed_result: Any,
        result_variable: str,
        usage: dict,
    ):
        prompt_message_data = ClassificationPromptMessageData(
            prompt_id=prompt_id,
            prompt_text=prompt_text,
            raw_response=raw_response,
            parsed_result=parsed_result,
            result_variable=result_variable,
            usage=usage,
        )
        graph_message = GraphMessage(
            session_id=session_id,
            name=node_name,
            execution_order=execution_order,
            message_data=prompt_message_data,
        )
        writer(graph_message)
        return graph_message
