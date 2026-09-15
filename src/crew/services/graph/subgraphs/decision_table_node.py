from dataclasses import asdict
import json
import uuid
from loguru import logger

from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.graph import START, END
from langgraph.types import StreamWriter

from models.graph_models import GraphMessage
from services.graph.events import StopEvent
from services.graph.custom_message_writer import CustomSessionMessageWriter
from src.crew.services.graph.session_audit_provider import emit_session_audit_event
from src.shared.models import (
    ConditionGroupData,
    DecisionTableNodeData,
    PythonCodeData,
)
from models.state import State

from services.run_python_code_service import RunPythonCodeService


class DecisionTableNodeDataError(Exception):
    """Custom exception for errors related to DecisionTableNodeData."""


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

    def _publish_message(self, graph_message: GraphMessage):
        """Publish a GraphMessage directly to Redis and dispatch it to the
        audit pipeline. Subgraph StreamWriter messages don't propagate to the
        parent graph's astream (same finding as
        ClassificationDecisionTableNodeSubgraph._publish_message), so without
        this, this node's start/finish/condition-group/error messages never
        reach Redis (hence never Postgres) or OpenSearch at all."""
        if self.redis_service is None:
            return
        try:
            data = asdict(graph_message)
        except (TypeError, Exception) as e:
            logger.warning(f"Failed to serialize GraphMessage via asdict: {e}")
            data = {
                "session_id": graph_message.session_id,
                "name": graph_message.name,
                "execution_order": graph_message.execution_order,
                "message_data": graph_message.message_data
                if isinstance(graph_message.message_data, dict)
                else {
                    "message_type": getattr(
                        graph_message.message_data, "message_type", "unknown"
                    )
                },
                "timestamp": graph_message.timestamp,
            }
        data["uuid"] = str(uuid.uuid4())
        self.redis_service.publish("graph:messages", data)
        try:
            emit_session_audit_event(data)
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
                expression=condition_group.expression,
                state=state,
            )

        return condition_group_result

    async def _execute_manipulation(
        self,
        manipulation: str | None,
        state: State,
    ) -> bool:
        if manipulation is None:
            return True

        code = f"""
def main(**kwargs) -> bool:
    variables = kwargs.get("variables", {{}})
    {manipulation}
    return variables
"""
        python_code_data = PythonCodeData(
            venv_name="default",
            code=code,
            entrypoint="main",
            libraries=[],
        )
        python_code_execution_data: dict = (
            await self.run_code_execution_service.run_code(
                python_code_data=python_code_data,
                inputs={"variables": state["variables"].model_dump()},
                stop_event=self.stop_event,
            )
        )

        logger.info(f"Python code execution data: {python_code_execution_data}")
        if python_code_execution_data["returncode"] != 0:
            raise DecisionTableNodeDataError(
                f"Manipulation execution failed with error: {python_code_execution_data['stderr']}"
            )

        variables = json.loads(python_code_execution_data["result_data"])
        state["variables"].update(variables)

    async def _execute_expression(
        self,
        expression: str,
        state: State,
    ) -> bool:
        code = f"""
def main(variables: dict) -> bool:
    result: bool = {expression}
    assert isinstance(result, bool), "Expression must return a boolean value"
    return result
"""

        python_code_data = PythonCodeData(
            venv_name="default",
            code=code,
            entrypoint="main",
            libraries=[],
        )

        python_code_execution_data: dict = (
            await self.run_code_execution_service.run_code(
                python_code_data=python_code_data,
                inputs={"variables": state["variables"].model_dump()},
                stop_event=self.stop_event,
            )
        )
        if python_code_execution_data["returncode"] != 0:
            raise DecisionTableNodeDataError(
                f"Expression execution failed with error: {python_code_execution_data['stderr']}"
            )
        return json.loads(python_code_execution_data["result_data"]) or False

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
            logger.info(
                f"Entering decision table node: {self.decision_table_node_data.node_name}"
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
                state["system_variables"]["nodes"][self.node_name].update(
                    update_variables
                )
            # Session-wide counter, not a per-node-name-local one - matches
            # BaseNode.run() and ClassificationDecisionTableNodeSubgraph's
            # own enter_node_function. This node used to keep its own
            # counter starting at 0 on every visit, independent of session
            # order entirely - so it always sorted to the very front of the
            # session's message list (even before the actual first node),
            # regardless of when it really ran.
            order = state["system_variables"].get("execution_order", 0)
            state["system_variables"]["execution_order"] = order + 1
            state["system_variables"]["nodes"][self.node_name][
                "execution_order"
            ] = order
            input_vars = state["variables"].model_dump()
            # "shared" is a live SharedVariables object injected onto flow
            # state (graph_session_manager_service.py), not JSON-serializable
            # - leaving it in poisons this event's audit write and, before
            # AuditClient's flush loop was hardened against a single bad
            # event, silently killed audit for the rest of the process.
            # Classification's own enter_node_function already strips it;
            # this one didn't.
            if "shared" in input_vars:
                del input_vars["shared"]
            msg = self.custom_session_message_writer.add_start_message(
                session_id=self.session_id,
                node_name=self.node_name,
                writer=writer,
                input_=input_vars,
                execution_order=self.execution_order(state),
                node_type=self.TYPE,
            )
            self._publish_message(msg)
            return state

        async def main_node_function(state: State, writer: StreamWriter):
            logger.info(
                f"Entering main decision table node: {self.decision_table_node_data.node_name}"
            )

            # Increment the last condition group index
            decision_node_variables = state["system_variables"]["nodes"][self.node_name]

            if decision_node_variables["result_node"] is not None:
                logger.info(
                    f"result_node is already set to {decision_node_variables['result_node']}, skipping condition groups."
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
                self._publish_message(msg)
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
                self._publish_message(msg)

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
                try:
                    logger.info(
                        f"Executing condition group: {condition_group.group_name}"
                    )
                    decision_node_variables = state["system_variables"]["nodes"][
                        self.node_name
                    ]
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
                    self._publish_message(msg)
                    if condition_result:
                        logger.info(
                            f"Condition group '{condition_group.group_name}' passed."
                        )
                        if condition_group.manipulation:
                            await self._execute_manipulation(
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
                            self._publish_message(msg)

                        decision_node_variables["result_node"] = (
                            condition_group.next_node
                        )
                except DecisionTableNodeDataError as e:
                    error = f"Error executing condition group '{condition_group.group_name}': {e}"
                    logger.error(error)
                    decision_node_variables["result_node"] = (
                        self.decision_table_node_data.next_error_node or END
                    )
                    decision_node_variables["next_node"] = END
                    msg = self.custom_session_message_writer.add_error_message(
                        session_id=self.session_id,
                        node_name=self.node_name,
                        error=error,
                        writer=writer,
                        execution_order=self.execution_order(state),
                        node_type=self.TYPE,
                    )
                    self._publish_message(msg)
                finally:
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
