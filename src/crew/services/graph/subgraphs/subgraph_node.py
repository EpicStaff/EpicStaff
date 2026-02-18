from utils import map_variables_to_input
from copy import deepcopy
from dotdict import DotDict
from models.request_models import SubGraphNodeData, GraphData, SubGraphData
from models.graph_models import (
    GraphMessage,
    SubGraphFinishMessageData,
    SubGraphStartMessageData,
)
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StreamWriter
from services.graph.custom_message_writer import CustomSessionMessageWriter
from utils.set_output_variables import set_output_variables


class SubGraphNode:
    def __init__(
        self,
        session_id: int,
        subgraph_node_data: SubGraphNodeData,
        unique_subgraph_list: list[SubGraphData],
        graph_builder: StateGraph,
        custom_session_message_writer: CustomSessionMessageWriter | None = None,
        session_graph_builder=None,
        stop_event=None,
    ):
        self.unique_subgraph_list = unique_subgraph_list
        self.subgraph_node_data = subgraph_node_data
        self._graph_builder = graph_builder
        self.session_id = session_id
        self.node_name = subgraph_node_data.node_name
        self.input_map = subgraph_node_data.input_map
        self.subgraph_data = self._get_graph_data(subgraph_node_data.subgraph_id)
        self.output_variable_path = subgraph_node_data.output_variable_path
        self.custom_session_message_writer = (
            custom_session_message_writer or CustomSessionMessageWriter()
        )
        self.session_graph_builder = session_graph_builder
        self.stop_event = stop_event

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
        """Create temporary session data for subgraph building."""
        from models.request_models import SessionData

        return SessionData(
            id=self.session_id,
            graph=self.subgraph_data.data,
            unique_subgraph_list=self.unique_subgraph_list,
            initial_state=initial_state,
        )

    def _create_subgraph_builder(self):
        """Create a new SessionGraphBuilder instance with inherited services."""
        from services.graph.graph_builder import SessionGraphBuilder

        return SessionGraphBuilder(
            session_id=self.session_id,
            redis_service=self.session_graph_builder.redis_service,
            crew_parser_service=self.session_graph_builder.crew_parser_service,
            python_code_executor_service=self.session_graph_builder.python_code_executor_service,
            crewai_output_channel=self.session_graph_builder.crewai_output_channel,
            knowledge_search_service=self.session_graph_builder.knowledge_search_service,
            stop_event=self.stop_event,
        )

    def _build_simple_graph(self) -> CompiledStateGraph:
        """Build simple graph without SessionGraphBuilder."""
        subgraph_data = self.subgraph_data.data
        self._graph_builder.set_entry_point(subgraph_data.data.entry_point)
        return self._graph_builder.compile()

    async def run(self, state, writer: StreamWriter):
        """Execute the subgraph and handle input/output mapping."""
        subgraph_input = self._prepare_subgraph_input(state)

        self._send_start_message(state, subgraph_input, writer)

        subgraph_state = self._create_subgraph_state(state, subgraph_input)
        compiled_subgraph = self.build(initial_state=subgraph_input)

        result = await self._execute_subgraph(compiled_subgraph, subgraph_state, writer)

        updated_state = self._process_subgraph_result(state, subgraph_input, result)

        self._send_finish_message(
            updated_state, result["variables"].model_dump(), writer
        )

        return {
            "variables": updated_state["variables"],
            "state_history": updated_state["state_history"],
        }

    def _prepare_subgraph_input(self, state) -> dict:
        """Map variables from parent state to subgraph input."""
        return map_variables_to_input(state["variables"], self.input_map)

    def _send_start_message(self, state, subgraph_input, writer: StreamWriter):
        """Send subgraph start message to writer."""
        start_message_data = SubGraphStartMessageData(
            state=self.custom_session_message_writer._convert_state(state=state),
            input=subgraph_input,
        )
        graph_message = GraphMessage(
            session_id=self.session_id,
            name=self.node_name,
            execution_order=0,
            message_data=start_message_data,
        )
        writer(graph_message)

    def _create_subgraph_state(self, state, subgraph_input) -> dict:
        """Create initial state for subgraph execution."""
        variables = self.subgraph_data.initial_state | subgraph_input

        return {
            "variables": DotDict(variables),
            "state_history": [],
            "system_variables": deepcopy(state.get("system_variables", {})),
        }

    async def _execute_subgraph(
        self, compiled_subgraph, subgraph_state, writer: StreamWriter
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
                    writer(data)
                elif stream_mode == "values":
                    result = data
            else:
                result = chunk

        if result is None:
            result = await compiled_subgraph.ainvoke(
                subgraph_state, {"recursion_limit": 1000}
            )

        return result

    def _process_subgraph_result(self, state, subgraph_input, result) -> dict:
        """Process subgraph result and update parent state."""
        subgraph_output = result["variables"].model_dump()

        temp_state = {"variables": DotDict(state["variables"].model_dump())}

        if self.output_variable_path == "variables":
            temp_state["variables"] = DotDict(subgraph_output)
        elif self.output_variable_path:
            if self.output_variable_path.startswith("variables."):
                full_path = self.output_variable_path
            else:
                full_path = f"variables.{self.output_variable_path}"

            set_output_variables(temp_state, full_path, subgraph_output)

        state_history_item = self._create_state_history_item(
            subgraph_input, subgraph_output, dict(temp_state["variables"])
        )

        return {
            "variables": temp_state["variables"],
            "state_history": state["state_history"] + [state_history_item],
            "system_variables": state.get("system_variables", {}),
        }

    def _create_state_history_item(
        self, subgraph_input, subgraph_output, updated_variables
    ) -> dict:
        """Create state history item for subgraph execution."""
        return {
            "type": "SUBGRAPH",
            "name": self.node_name,
            "additional_data": {
                "input_map": self.input_map,
                "output_variable_path": self.output_variable_path,
            },
            "input": subgraph_input,
            "output": subgraph_output,
            "variables": updated_variables,
        }

    def _send_finish_message(
        self, updated_state, subgraph_output, writer: StreamWriter
    ):
        """Send subgraph finish message to writer."""
        finish_message_data = SubGraphFinishMessageData(
            state=self.custom_session_message_writer._convert_state(
                state=updated_state
            ),
            output=subgraph_output,
        )
        graph_message = GraphMessage(
            session_id=self.session_id,
            name=self.node_name,
            execution_order=0,
            message_data=finish_message_data,
        )
        writer(graph_message)

    def _get_graph_data(self, graph_id: int) -> GraphData:
        subgraph = next(
            (sg for sg in self.unique_subgraph_list if sg.id == graph_id), None
        )
        return subgraph if subgraph else None
