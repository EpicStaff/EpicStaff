from copy import deepcopy
from uuid import uuid4

from dotdict import DotDict
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter
from loguru import logger
from models.graph_models import (
    GraphMessage,
    SubGraphFinishMessageData,
    SubGraphStartMessageData,
    dataclass_to_shallow_dict,
)
from services.graph.custom_message_writer import CustomSessionMessageWriter
from services.graph.exceptions import InvalidStatePathError, StopSession
from src.shared.models import GraphData, SubGraphData, SubGraphNodeData
from src.shared.models.storage_scope import StorageCredentials
from utils import map_variables_to_input
from utils.node_label import runtime_node_name_to_label
from utils.set_output_variables import set_output_variables
from utils.state_path import split_state_path


class SubGraphNode:
    TYPE = "SUBGRAPH"
    LABEL = "Subflow node"

    def __init__(
        self,
        session_id: int,
        subgraph_node_data: SubGraphNodeData,
        unique_subgraph_list: list[SubGraphData],
        graph_builder: StateGraph,
        org_id: int,
        audit_retention_days: int,
        custom_session_message_writer: CustomSessionMessageWriter | None = None,
        session_graph_builder=None,
        stop_event=None,
        storage_credentials: StorageCredentials | None = None,
        storage_credentials_by_grant: dict[str, StorageCredentials] | None = None,
    ):
        self.unique_subgraph_list = unique_subgraph_list
        self.subgraph_node_data = subgraph_node_data
        self._graph_builder = graph_builder
        self.session_id = session_id
        self.org_id = org_id
        self.audit_retention_days = audit_retention_days
        self.node_name = subgraph_node_data.node_name
        self.input_map = subgraph_node_data.input_map
        self.subgraph_data = self._get_graph_data(subgraph_node_data.subgraph_id)
        self.output_variable_path = subgraph_node_data.output_variable_path
        self.custom_session_message_writer = (
            custom_session_message_writer or CustomSessionMessageWriter()
        )
        self.session_graph_builder = session_graph_builder
        self.stop_event = stop_event
        self.storage_credentials = storage_credentials
        self.storage_credentials_by_grant = storage_credentials_by_grant or {}
        self._compiled_subgraph: CompiledStateGraph | None = None

    def build(self, initial_state) -> CompiledStateGraph:
        """
        Builds and compiles the subgraph from subgraph_data.
        Recursively builds the entire graph structure using SessionGraphBuilder pattern.
        """
        if self.session_graph_builder:
            return self._build_with_session_graph_builder(initial_state)
        else:
            return self._build_simple_graph()

    def _build_with_session_graph_builder(self, initial_state) -> CompiledStateGraph:
        """Build subgraph using SessionGraphBuilder for complex scenarios."""
        temp_session_data = self._create_temp_session_data(initial_state)
        subgraph_builder = self._create_subgraph_builder()

        return subgraph_builder.compile_from_schema(temp_session_data)

    def _create_temp_session_data(self, initial_state):
        """Create temporary session data for subgraph building.

        Carries the parent session's storage credentials so storage-demanding nodes
        nested inside the subgraph are built with the same credentials.
        """
        from src.shared.models import SessionData

        return SessionData(
            id=self.session_id,
            graph=self.subgraph_data.data,
            unique_subgraph_list=self.unique_subgraph_list,
            initial_state=initial_state,
            storage_credentials=self.storage_credentials,
            storage_credentials_by_grant=self.storage_credentials_by_grant,
            org_id=self.org_id,
            audit_retention_days=self.audit_retention_days,
        )

    def _create_subgraph_builder(self):
        """Create a new SessionGraphBuilder instance with inherited services."""
        from services.graph.graph_builder import SessionGraphBuilder

        return SessionGraphBuilder(
            session_id=self.session_id,
            redis_service=self.session_graph_builder.redis_service,
            python_code_executor_service=self.session_graph_builder.python_code_executor_service,
            knowledge_search_service=self.session_graph_builder.knowledge_search_service,
            agent_task_service=self.session_graph_builder.agent_task_service,
            key_value_client=self.session_graph_builder.key_value_client,
            secrets_cryptographer=self.session_graph_builder.secrets_cryptographer,
            stop_event=self.stop_event,
        )

    def _build_simple_graph(self) -> CompiledStateGraph:
        """Build simple graph without SessionGraphBuilder."""
        subgraph_data = self.subgraph_data.data
        self._graph_builder.set_entry_point(subgraph_data.data.entrypoint)
        return self._graph_builder.compile()

    async def run(self, state, writer: StreamWriter):
        """Execute the subgraph and handle input/output mapping.

        A failure streams an error card naming this node, then propagates. Its text is a
        fixed fact: the raw error is logged, never streamed. A stop (StopSession) propagates
        without a card.
        """
        subgraph_execution_id = str(uuid4())
        sysvars = state.get("system_variables") or {}
        state["system_variables"] = sysvars  # ensure attached before deep-copy

        try:
            subgraph_input = self._prepare_subgraph_input(state)
            # Rejected before the child flow runs, which would otherwise do its work for nothing.
            if self.output_variable_path:
                split_state_path(self.output_variable_path)

            start_order = sysvars.get("execution_order", 0)
            sysvars["execution_order"] = start_order + 1
            self._send_start_message(
                state,
                subgraph_input,
                writer,
                subgraph_execution_id,
                execution_order=start_order,
            )

            subgraph_state = self._create_subgraph_state(state, subgraph_input)
            # Compiled lazily, not in __init__: a subflow that contains itself would recurse forever.
            if self._compiled_subgraph is None:
                self._compiled_subgraph = self.build(initial_state=subgraph_input)
        # A stop is not a failure of this node: it needs no error card of its own.
        except StopSession:
            raise
        except Exception as error:
            if self.subgraph_data is None:
                fact = f"{self._display_name()} couldn't start its flow."
            else:
                fact = f'{self._display_name()} couldn\'t start flow "{self._flow_name()}".'
            self._send_error_message(sysvars, writer, error, fact)
            raise

        try:
            result = await self._execute_subgraph(
                self._compiled_subgraph, subgraph_state, writer, subgraph_execution_id
            )

            # advance parent counter past the range the child consumed
            child_order = (result.get("system_variables") or {}).get(
                "execution_order", sysvars["execution_order"]
            )
            sysvars["execution_order"] = max(sysvars["execution_order"], child_order)

            updated_state = self._process_subgraph_result(state, subgraph_input, result)
        except StopSession:
            raise
        except Exception as error:
            fact = f'{self._display_name()} couldn\'t finish flow "{self._flow_name()}".'
            self._send_error_message(sysvars, writer, error, fact)
            raise

        finish_order = sysvars["execution_order"]
        sysvars["execution_order"] = finish_order + 1
        self._send_finish_message(
            updated_state,
            result["variables"].model_dump(),
            writer,
            subgraph_execution_id,
            execution_order=finish_order,
        )

        return {
            "variables": updated_state["variables"],
            "state_history": updated_state["state_history"],
            "system_variables": sysvars,
        }

    def _prepare_subgraph_input(self, state) -> dict:
        """Map variables from parent state to subgraph input."""
        return map_variables_to_input(state["variables"], self.input_map)

    def _send_start_message(
        self,
        state,
        subgraph_input,
        writer: StreamWriter,
        subgraph_execution_id,
        execution_order: int = 0,
    ):
        """Send subgraph start message to writer."""
        start_message_data = SubGraphStartMessageData(
            state=self.custom_session_message_writer._convert_state(state=state),
            input=subgraph_input,
            subgraph_execution_id=subgraph_execution_id,
            subgraph_id=self.subgraph_node_data.subgraph_id,
        )
        graph_message = GraphMessage(
            session_id=self.session_id,
            name=self.node_name,
            execution_order=execution_order,
            message_data=start_message_data,
            node_type=self.TYPE,
        )
        writer(graph_message)

    def _create_subgraph_state(self, state, subgraph_input) -> dict:
        """Create initial state for subgraph execution."""
        variables = self.subgraph_data.initial_state | subgraph_input

        return {
            "variables": DotDict(variables),
            "state_history": [],
            "system_variables": deepcopy(state.get("system_variables", {})),
            "execution_counts": {},
        }

    async def _execute_subgraph(
        self,
        compiled_subgraph,
        subgraph_state,
        writer: StreamWriter,
        subgraph_execution_id,
    ):
        """Execute the compiled subgraph and stream results."""
        result = None

        async for chunk in compiled_subgraph.astream(
            subgraph_state,
            config={"recursion_limit": 1000},
            stream_mode=["values", "custom"],
        ):
            if isinstance(chunk, tuple):
                stream_mode, data = chunk
                if stream_mode == "custom":
                    if isinstance(data, GraphMessage):
                        msg_data = data.message_data

                        if not isinstance(msg_data, dict):
                            msg_data = dataclass_to_shallow_dict(msg_data)
                            data.message_data = msg_data

                        existing = msg_data.get("subgraph_execution_ids") or []
                        msg_data["subgraph_execution_ids"] = [*existing, subgraph_execution_id]
                    writer(data)
                elif stream_mode == "values":
                    result = data
            else:
                result = chunk

        if result is None:
            result = await compiled_subgraph.ainvoke(subgraph_state, {"recursion_limit": 1000})

        return result

    def _process_subgraph_result(self, state, subgraph_input, result) -> dict:
        """Process subgraph result and update parent state."""
        # No copy needed: set_output_variables copies containers on assignment (DotDict._copy_wrap).
        subgraph_output = result["variables"]

        temp_state = {"variables": DotDict(state["variables"].deep_dump())}

        if self.output_variable_path:
            if self.output_variable_path == "variables" or self.output_variable_path.startswith(
                "variables."
            ):
                full_path = self.output_variable_path
            else:
                full_path = f"variables.{self.output_variable_path}"

            try:
                set_output_variables(temp_state, full_path, subgraph_output)
            # Raised when a segment of the path is missing or can't hold the next one.
            except (IndexError, KeyError, TypeError, AttributeError) as error:
                raise InvalidStatePathError(
                    f'Output path "{self.output_variable_path}" of {self._display_name()} '
                    "doesn't exist."
                ) from error

        state_history_item = self._create_state_history_item(subgraph_input, subgraph_output)

        counts = dict(state.get("execution_counts", {}))
        counts[self.node_name] = counts.get(self.node_name, 0) + 1

        return {
            "variables": temp_state["variables"],
            "state_history": state["state_history"] + [state_history_item],
            "system_variables": state.get("system_variables", {}),
            "execution_counts": counts,
        }

    def _create_state_history_item(self, subgraph_input, subgraph_output) -> dict:
        """Create state history item for subgraph execution."""
        return {
            "type": self.TYPE,
            "name": self.node_name,
            "additional_data": {
                "input_map": self.input_map,
                "output_variable_path": self.output_variable_path,
            },
            "input": subgraph_input,
            "output": subgraph_output,
        }

    def _send_finish_message(
        self,
        updated_state,
        subgraph_output,
        writer: StreamWriter,
        subgraph_execution_id,
        execution_order: int = 0,
    ):
        """Send subgraph finish message to writer."""
        finish_message_data = SubGraphFinishMessageData(
            state=self.custom_session_message_writer._convert_state(state=updated_state),
            output=subgraph_output,
            subgraph_execution_id=subgraph_execution_id,
        )
        graph_message = GraphMessage(
            session_id=self.session_id,
            name=self.node_name,
            execution_order=execution_order,
            message_data=finish_message_data,
            node_type=self.TYPE,
        )
        writer(graph_message)

    def _send_error_message(self, sysvars: dict, writer: StreamWriter, error: Exception, fact: str):
        """Stream this node's error card: the error's own text when it is written for the
        user, otherwise `fact`. The raw error is logged at WARNING: it propagates to the
        session, which logs it at ERROR."""
        execution_order = sysvars.get("execution_order", 0)
        sysvars["execution_order"] = execution_order + 1
        if isinstance(error, InvalidStatePathError):
            public_details = str(error)
        else:
            logger.opt(exception=error).warning(
                "Subflow node failed: {error} (session_id={session_id}, node_name={node_name})",
                error=str(error),
                session_id=self.session_id,
                node_name=self.node_name,
            )
            public_details = fact
        self.custom_session_message_writer.add_error_message(
            session_id=self.session_id,
            node_name=self.node_name,
            writer=writer,
            execution_order=execution_order,
            node_type=self.TYPE,
            error=error,
            public_details=public_details,
        )

    def _display_name(self) -> str:
        return f'{self.LABEL} "{runtime_node_name_to_label(self.node_name)}"'

    def _flow_name(self) -> str:
        return self.subgraph_data.data.name

    def _get_graph_data(self, graph_id: int) -> GraphData:
        subgraph = next((sg for sg in self.unique_subgraph_list if sg.id == graph_id), None)
        return subgraph if subgraph else None
