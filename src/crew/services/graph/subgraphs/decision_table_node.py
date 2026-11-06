import json

from foundation.utils.error_reference import log_with_reference
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter
from loguru import logger
from models.graph_models import GraphMessage
from models.state import State
from services.graph.custom_message_writer import CustomSessionMessageWriter
from services.graph.events import StopEvent
from services.graph.exceptions import NodeExecutionError, StopSession
from services.graph.subgraphs.decision_table_errors import (
    CONDITION_FAILURE_SOURCE,
    ConditionFailure,
    DecisionTableError,
    UserCodePart,
    check_code_ran,
    condition_error,
    condition_subject,
    manipulation_error,
    unreadable_result_error,
)
from services.run_python_code_service import RunPythonCodeService
from src.crew.services.graph.session_audit_provider import emit_session_audit_event
from src.shared.models import (
    ConditionGroupData,
    DecisionTableNodeData,
    PythonCodeData,
)
from src.shared.models.storage_scope import StorageCredentials
from src.shared.public_error import PublicErrorMessage, build_public_error_message

# The expression arrives as data and is compiled on its own, so an error in it is reported
# as the expression's, not as a line of this code. It sees what it saw when it was pasted
# into main(): `variables`, then the sandbox module globals.
_EVALUATE_CONDITION_CODE = (
    CONDITION_FAILURE_SOURCE
    + """

def main(expression, variables):
    try:
        result = eval(
            compile(expression, "<condition>", "eval"), {**globals(), "variables": variables}
        )
    # BaseException so that exit() in an expression is reported as the condition's error.
    except BaseException as error:
        return {"result": None, "error": _condition_failure(error)}
    if not isinstance(result, bool):
        return {"result": None, "error": _NOT_BOOLEAN_FAILURE}
    return {"result": result, "error": None}
"""
)

# The manipulation is pasted after the indentation of its first line, so it can span
# lines only if the user indents every further line.
_MANIPULATION_CODE_PREFIX = """
def main(**kwargs) -> bool:
    variables = kwargs.get("variables", {})
    """
_MANIPULATION_CODE_SUFFIX = """
    return variables
"""


class DecisionTableNodeSubgraph:
    TYPE = "DECISION_TABLE"

    def __init__(
        self,
        session_id: int,
        decision_table_node_data: DecisionTableNodeData,
        graph_builder: StateGraph,
        stop_event: StopEvent,
        run_code_execution_service: RunPythonCodeService,
        redis_service=None,
        custom_session_message_writer: CustomSessionMessageWriter | None = None,
        storage_credentials: StorageCredentials | None = None,
    ):
        self.decision_table_node_data = decision_table_node_data
        self._graph_builder = graph_builder
        self.session_id = session_id
        self.node_name = decision_table_node_data.node_name
        self.stop_event = stop_event
        self.input_map = None
        self.output_variable_path = None
        self.redis_service = redis_service
        self.custom_session_message_writer = (
            custom_session_message_writer or CustomSessionMessageWriter()
        )
        self.run_code_execution_service = run_code_execution_service
        self.storage_credentials = storage_credentials

    async def _publish_message(self, graph_message: GraphMessage):
        """Publish a GraphMessage directly to Redis and dispatch it to the
        audit pipeline. Subgraph StreamWriter messages don't propagate to the
        parent graph's astream (same finding as
        ClassificationDecisionTableNodeSubgraph._publish_message), so without
        this, this node's start/finish/condition-group/error messages never
        reach Redis (hence never Postgres) or OpenSearch at all."""
        if self.redis_service is None:
            return
        data = graph_message.to_payload()
        encoded_data = GraphMessage.encode_payload(data)
        await self.redis_service.aadd_graph_message(data["uuid"], encoded_data)
        try:
            emit_session_audit_event(encoded_data)
        except Exception as audit_exc:
            logger.warning(f"Audit dispatch failed, dropping: {audit_exc}")

    async def _execute_condition_group(
        self,
        condition_group: ConditionGroupData,
        state: State,
    ) -> bool:
        condition_group_result: bool = False
        if condition_group.group_type == "simple":
            for condition in condition_group.condition_list:
                if not await self._execute_expression(
                    condition_name=condition_group.group_name,
                    expression=condition.condition,
                    state=state,
                ):
                    condition_group_result = False
                    break
            else:
                condition_group_result = True

        elif condition_group.group_type == "complex":
            if condition_group.expression is None:
                logger.error("Complex condition group must have an expression")
                return False
            condition_group_result = await self._execute_expression(
                condition_name=condition_group.group_name,
                expression=condition_group.expression,
                state=state,
            )

        return condition_group_result

    async def _execute_manipulation(
        self,
        condition_name: str,
        manipulation: str | None,
        state: State,
    ) -> bool:
        if manipulation is None:
            return True

        code = _MANIPULATION_CODE_PREFIX + manipulation + _MANIPULATION_CODE_SUFFIX
        manipulation_part = UserCodePart(
            label="manipulation code",
            first_line=_MANIPULATION_CODE_PREFIX.count("\n") + 1,
            line_count=manipulation.count("\n") + 1,
            shows_line_numbers=True,
        )
        python_code_data = PythonCodeData(
            code=code,
            entrypoint="main",
        )
        python_code_execution_data = await self.run_code_execution_service.run_code(
            python_code_data=python_code_data,
            inputs={"variables": state["variables"].model_dump()},
            stop_event=self.stop_event,
            storage_credentials=self.storage_credentials,
        )

        logger.debug(
            "Manipulation finished: execution_id={} returncode={}",
            python_code_execution_data.execution_id,
            python_code_execution_data.returncode,
        )
        check_code_ran(python_code_execution_data, condition_subject(condition_name))
        if python_code_execution_data.failure is not None:
            raise manipulation_error(
                condition_name, python_code_execution_data.failure, [manipulation_part]
            )

        try:
            variables = json.loads(python_code_execution_data.result_data)
        except (TypeError, ValueError) as error:
            raise unreadable_result_error(
                condition_subject(condition_name), python_code_execution_data.result_data
            ) from error
        state["variables"].update(variables)

    async def _execute_expression(
        self,
        condition_name: str,
        expression: str,
        state: State,
    ) -> bool:
        subject = condition_subject(condition_name)
        python_code_execution_data = await self.run_code_execution_service.run_code(
            python_code_data=PythonCodeData(code=_EVALUATE_CONDITION_CODE, entrypoint="main"),
            # Stripped: unlike the assignment it used to be pasted into, compile() in "eval"
            # mode rejects leading spaces.
            inputs={
                "expression": expression.strip(),
                "variables": state["variables"].model_dump(),
            },
            stop_event=self.stop_event,
            storage_credentials=self.storage_credentials,
        )
        check_code_ran(python_code_execution_data, subject)
        if python_code_execution_data.failure is not None:
            # The evaluation reports the expression's own errors in its result, so this is
            # the sandbox stopping the code, e.g. at its time limit.
            raise DecisionTableError(f"{subject}: {python_code_execution_data.failure.detail}")

        result_data = python_code_execution_data.result_data
        try:
            evaluation = json.loads(result_data)
            failure = ConditionFailure.from_result(evaluation["error"])
            result = evaluation["result"]
        except (TypeError, ValueError, KeyError) as error:
            raise unreadable_result_error(subject, result_data) from error
        if failure is not None:
            raise condition_error(condition_name, failure)
        if not isinstance(result, bool):
            raise unreadable_result_error(subject, result_data)
        return result

    async def _fail(
        self,
        state: State,
        writer: StreamWriter,
        error: Exception,
        public_message: str,
        reference: str | None,
    ) -> None:
        """Show the error, then take the error route, or fail the session if there is none.

        Raises:
            NodeExecutionError: The node has no error route; the session fails repeating
                `public_message`.
        """
        msg = self.custom_session_message_writer.add_error_message(
            session_id=self.session_id,
            node_name=self.node_name,
            writer=writer,
            execution_order=self.execution_order(state),
            node_type=self.TYPE,
            public_details=public_message,
        )
        await self._publish_message(msg)
        next_error_node = self.decision_table_node_data.next_error_node
        if next_error_node is None:
            raise NodeExecutionError(public_message, reference=reference) from error
        decision_node_variables = state["system_variables"]["nodes"][self.node_name]
        decision_node_variables["result_node"] = next_error_node
        decision_node_variables["next_node"] = END

    def execution_order(self, state: State):
        return state["system_variables"]["nodes"][self.node_name]["execution_order"]

    def build(self) -> CompiledStateGraph:
        """
        Build the decision table node and add it to the graph builder.
        This function creates the necessary nodes and edges for the decision table.

        Returns:
            CompiledStateGraph: The name of the enter node for the decision table.
        """

        enter_node = self.decision_table_node_data.node_name
        main_node = self.decision_table_node_data.node_name + "_main"

        async def enter_node_function(state: State, writer: StreamWriter):
            logger.debug(
                "Entering decision table node: {}", self.decision_table_node_data.node_name
            )

            # update variables
            update_variables = {
                "last_condition_group_index": -1,
                "next_node": None,
                "result_node": None,
                "default_node": self.decision_table_node_data.default_next_node,  # TODO: rename it to result or smt
            }
            if state["system_variables"].get("nodes") is None:
                state["system_variables"]["nodes"] = {}
            if state["system_variables"]["nodes"].get(self.node_name) is None:
                state["system_variables"]["nodes"][self.node_name] = update_variables
            else:
                state["system_variables"]["nodes"][self.node_name].update(update_variables)
            # Session-wide counter, not a per-node-name-local one - matches
            # BaseNode.run() and ClassificationDecisionTableNodeSubgraph's
            # own enter_node_function. This node used to keep its own
            # counter starting at 0 on every visit, independent of session
            # order entirely - so it always sorted to the very front of the
            # session's message list (even before the actual first node),
            # regardless of when it really ran.
            order = state["system_variables"].get("execution_order", 0)
            state["system_variables"]["execution_order"] = order + 1
            state["system_variables"]["nodes"][self.node_name]["execution_order"] = order
            input_vars = state["variables"].model_dump()
            msg = self.custom_session_message_writer.add_start_message(
                session_id=self.session_id,
                node_name=self.node_name,
                writer=writer,
                input_=input_vars,
                execution_order=self.execution_order(state),
                node_type=self.TYPE,
            )
            await self._publish_message(msg)
            return state

        async def main_node_function(state: State, writer: StreamWriter):
            logger.debug(
                "Entering main decision table node: {}",
                self.decision_table_node_data.node_name,
            )

            # Increment the last condition group index
            decision_node_variables = state["system_variables"]["nodes"][self.node_name]

            if decision_node_variables["result_node"] is not None:
                logger.debug(
                    "result_node is already set to {}, skipping condition groups.",
                    decision_node_variables["result_node"],
                )
                decision_node_variables["next_node"] = END
                msg = self.custom_session_message_writer.add_finish_message(
                    session_id=self.session_id,
                    node_name=self.node_name,
                    writer=writer,
                    output=decision_node_variables["result_node"],
                    execution_order=self.execution_order(state),
                    state=state,
                    node_type=self.TYPE,
                )
                await self._publish_message(msg)
                return state

            decision_node_variables["last_condition_group_index"] = (
                decision_node_variables["last_condition_group_index"] + 1
            )

            # Check if all condition groups have been processed
            if decision_node_variables["last_condition_group_index"] >= len(
                self.decision_table_node_data.conditional_group_list
            ):
                # If all condition groups are processed, go to the default next node
                decision_node_variables["result_node"] = (
                    self.decision_table_node_data.default_next_node or END
                )
                decision_node_variables["next_node"] = END
                msg = self.custom_session_message_writer.add_finish_message(
                    session_id=self.session_id,
                    node_name=self.node_name,
                    writer=writer,
                    output=decision_node_variables["result_node"],
                    execution_order=self.execution_order(state),
                    state=state,
                    node_type=self.TYPE,
                )
                await self._publish_message(msg)

            # If not, set the next node to the current condition group
            else:
                decision_node_variables["next_node"] = (
                    f"{self.decision_table_node_data.node_name}_condition_group_{decision_node_variables['last_condition_group_index']}"
                )

            return state

        async def conditional_edge_function(state: State, writer: StreamWriter):
            # This function is called when the enter node is executed
            return state["system_variables"]["nodes"][self.node_name]["next_node"]

        def condition_group_wrapper(
            condition_group: ConditionGroupData,
        ) -> callable:
            async def condition_group_function(state: State, writer: StreamWriter):
                decision_node_variables = state["system_variables"]["nodes"][self.node_name]
                try:
                    logger.debug("Executing condition group: {}", condition_group.group_name)
                    condition_result = await self._execute_condition_group(
                        condition_group=condition_group,
                        state=state,
                    )
                    msg = self.custom_session_message_writer.add_condition_group_message(
                        session_id=self.session_id,
                        node_name=self.node_name,
                        group_name=condition_group.group_name,
                        result=condition_result,
                        writer=writer,
                        execution_order=self.execution_order(state),
                    )
                    await self._publish_message(msg)
                    if condition_result:
                        logger.debug("Condition group '{}' passed.", condition_group.group_name)
                        if condition_group.manipulation:
                            await self._execute_manipulation(
                                condition_name=condition_group.group_name,
                                manipulation=condition_group.manipulation,
                                state=state,
                            )
                            msg = self.custom_session_message_writer.add_condition_group_manipulation_message(
                                session_id=self.session_id,
                                node_name=self.node_name,
                                group_name=condition_group.group_name,
                                state=state,
                                writer=writer,
                                execution_order=self.execution_order(state),
                            )
                            await self._publish_message(msg)

                        decision_node_variables["result_node"] = condition_group.next_node
                except StopSession:
                    raise
                except DecisionTableError as error:
                    logger.warning("Decision table '{}' failed: {}", self.node_name, error)
                    await self._fail(state, writer, error, str(error), error.reference)
                except Exception as error:
                    # The exception text can quote variables or code, so it stays in the
                    # log; the user sees a reference to that log line.
                    reference = log_with_reference(
                        "Decision table '{}' failed in condition '{}': {}: {}",
                        self.node_name,
                        condition_group.group_name,
                        type(error).__name__,
                        error,
                        exception=error,
                    )
                    public_message = build_public_error_message(
                        PublicErrorMessage.NODE_EXECUTION_FAILED, reference
                    )
                    await self._fail(state, writer, error, public_message, reference)

                return state

            return condition_group_function

        self._graph_builder.add_node(enter_node, enter_node_function)
        self._graph_builder.add_node(main_node, main_node_function)
        self._graph_builder.add_edge(START, enter_node)

        self._graph_builder.add_edge(enter_node, main_node)
        self._graph_builder.add_conditional_edges(main_node, conditional_edge_function)
        for condition_index, condition_group in enumerate(
            self.decision_table_node_data.conditional_group_list
        ):
            condition_group_name = f"{self.node_name}_condition_group_{condition_index}"
            self._graph_builder.add_node(
                condition_group_name,
                condition_group_wrapper(condition_group=condition_group),
            )
            self._graph_builder.add_edge(condition_group_name, main_node)

        return self._graph_builder.compile()
