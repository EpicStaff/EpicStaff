from typing import Any

from langgraph.types import StreamWriter
from loguru import logger
from models.graph_models import (
    ClassificationPromptMessageData,
    ConditionGroupMessageData,
    ConditonGroupManipulationMessageData,
    ErrorMessageData,
    FinishMessageData,
    GraphMessage,
    StartMessageData,
)
from models.state import State
from utils.node_label import runtime_node_name_to_label


class CustomSessionMessageWriter:
    """
    Upstream stream-message producer: builds GraphMessage objects onto the
    LangGraph StreamWriter for the primary Redis-backed pipeline. Unrelated
    to (and unaware of) src.shared.audit.writers.session_writer.SessionAuditWriter,
    which fans these same messages out to the audit trail downstream, in
    session_audit_provider.py::emit_session_audit_event - despite sharing
    the method name `add_custom_message`, the two classes are different
    concepts in series, not duplicates of each other.
    """

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
        node_type: str = "",
    ):
        """
        Add a start message to the graph.

        Args:
            writer (StreamWriter): A stream writer to write the message to.
            input_ (Any): The input to the node.
            execution_order (int): The order of execution of the node.
            node_type (str): The emitting node's BaseNode.TYPE, audit-only.
        """
        start_message_data = StartMessageData(
            input=input_,
        )
        graph_message = GraphMessage(
            session_id=session_id,
            name=node_name,
            execution_order=execution_order,
            message_data=start_message_data,
            node_type=node_type,
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
        node_type: str = "",
        **kwargs,
    ):
        """
        Add a finish message to the graph.

        Args:
            writer (StreamWriter): A stream writer to write the message to.
            output (Any): The output of the node.
            execution_order (int): The order of execution of the node.
            state (State): The current state of the graph.
            node_type (str): The emitting node's BaseNode.TYPE, audit-only.
            **kwargs: Additional data to include in the finish message.

        This function creates a finish message containing the node's output,
        current state variables, and state history. It also includes any
        additional data passed as keyword arguments. The message is then
        written using the provided stream writer.
        """

        finish_message_data = FinishMessageData(
            output=output,
            state=cls._convert_state(state=state),
            additional_data=kwargs,
        )
        graph_message = GraphMessage(
            session_id=session_id,
            name=node_name,
            execution_order=execution_order,
            message_data=finish_message_data,
            node_type=node_type,
        )
        writer(graph_message)
        return graph_message

    @classmethod
    def add_error_message(
        cls,
        session_id: int,
        node_name: str,
        writer: StreamWriter,
        execution_order: int,
        node_type: str = "",
        *,
        error: Exception | str | None = None,
        public_details: str | None = None,
    ):
        """
        Add an error message to the graph.

        When no `public_details` is supplied, the raw error is logged with the
        session and node, and the stream gets the fixed fact `Node "<name>" failed.`:
        raw text can carry credentials or internal hosts. `public_details`, when
        supplied, is streamed verbatim instead, and nothing extra is logged here:
        it is the caller's responsibility to only pass text that is already safe
        to show and to log the raw error itself if it needs to.

        Args:
            writer (StreamWriter): A stream writer to write the message to.
            execution_order (int): The order of execution of the node.
            node_type (str): The emitting node's BaseNode.TYPE, audit-only.
            error (Exception | str | None): The exception or error text that
                was raised. Required when `public_details` is omitted (it is
                what gets logged); ignored otherwise.
            public_details (str | None): Already-safe text to stream instead of
                the fixed fact. Callers pass this for domain errors whose
                wording is meant for the user. Not sanitized by this method.
        """
        if public_details is None:
            logger.opt(exception=error if isinstance(error, Exception) else None).error(
                "Node execution failed: {error} (session_id={session_id}, node_name={node_name})",
                error=str(error),
                session_id=session_id,
                node_name=node_name,
            )
            details = f'Node "{runtime_node_name_to_label(node_name)}" failed.'
        else:
            details = public_details
        error_message_data = ErrorMessageData(
            details=details,
        )
        graph_message = GraphMessage(
            session_id=session_id,
            name=node_name,
            execution_order=execution_order,
            message_data=error_message_data,
            node_type=node_type,
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
        provider: str | None = None,
        model_version: str | None = None,
    ):
        prompt_message_data = ClassificationPromptMessageData(
            prompt_id=prompt_id,
            prompt_text=prompt_text,
            raw_response=raw_response,
            parsed_result=parsed_result,
            result_variable=result_variable,
            usage=usage,
            provider=provider,
            model_version=model_version,
        )
        graph_message = GraphMessage(
            session_id=session_id,
            name=node_name,
            execution_order=execution_order,
            message_data=prompt_message_data,
        )
        writer(graph_message)
        return graph_message
