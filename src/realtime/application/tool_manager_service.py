from domain.models.realtime_tool import RealtimeTool
from domain.ports.i_chat_mode_controller import IChatModeController
from domain.ports.i_redis_messaging_service import IRedisMessagingService
from domain.ports.i_python_code_executor_service import IPythonCodeExecutorService
from src.shared.models import (
    ConfiguredToolData,
    PythonCodeToolData,
    RealtimeAgentChatData,
)
from tool_executors.stop_agent_tool_executor import StopAgentToolExecutor
from utils.singleton_meta import SingletonMeta
from tool_executors import (
    ConfiguredToolExecutor,
    PythonCodeToolExecutor,
    KnowledgeSearchToolExecutor,
    BaseToolExecutor,
)


class ToolManagerService(metaclass=SingletonMeta):
    def __init__(
        self,
        redis_service: IRedisMessagingService,
        python_code_executor_service: IPythonCodeExecutorService,
        knowledge_search_get_channel: str,
        knowledge_search_response_channel: str,
        manager_host: str,
        manager_port: int,
    ):
        self.knowledge_search_get_channel = knowledge_search_get_channel
        self.knowledge_search_response_channel = knowledge_search_response_channel
        self.manager_host = manager_host
        self.manager_port = manager_port
        self.redis_service = redis_service
        self.python_code_executor_service = python_code_executor_service
        self.connection_tool_executors: dict[str, list[BaseToolExecutor]] = {}

    def register_tools_from_rt_agent_chat_data(
        self,
        realtime_agent_chat_data: RealtimeAgentChatData,
        chat_mode_controller: IChatModeController | None = None,
    ) -> None:
        connection_key = realtime_agent_chat_data.connection_key
        self.connection_tool_executors[connection_key] = []

        if chat_mode_controller is not None:
            stop_agent_tool_executor = StopAgentToolExecutor(
                stop_prompt=realtime_agent_chat_data.stop_prompt,
                chat_mode_controller=chat_mode_controller,
            )
            self.connection_tool_executors[connection_key].append(
                stop_agent_tool_executor
            )

        if (
            realtime_agent_chat_data.knowledge_collection_id is not None
            and realtime_agent_chat_data.rag_type_id is not None
        ):
            rag_search_config = None
            if realtime_agent_chat_data.rag_search_config:
                rag_search_config = (
                    realtime_agent_chat_data.rag_search_config.model_dump()
                )

            knowledge_tool_executor = KnowledgeSearchToolExecutor(
                knowledge_collection_id=realtime_agent_chat_data.knowledge_collection_id,
                rag_type_id=realtime_agent_chat_data.rag_type_id,
                rag_search_config=rag_search_config,
                redis_service=self.redis_service,
                knowledge_search_get_channel=self.knowledge_search_get_channel,
                knowledge_search_response_channel=self.knowledge_search_response_channel,
                rag_embedder_api_key=realtime_agent_chat_data.rag_embedder_api_key,
            )
            self.connection_tool_executors[connection_key].append(
                knowledge_tool_executor
            )

        for base_tool_data in realtime_agent_chat_data.tools:
            tool_data = base_tool_data.data
            if isinstance(tool_data, ConfiguredToolData):
                tool_executor = ConfiguredToolExecutor(
                    configured_tool_data=tool_data,
                    host=self.manager_host,
                    port=self.manager_port,
                )

            elif isinstance(tool_data, PythonCodeToolData):
                tool_executor = PythonCodeToolExecutor(
                    python_code_tool_data=tool_data,
                    python_code_executor_service=self.python_code_executor_service,
                )
            else:
                raise ValueError(
                    f"Unknown tool data type: {type(tool_data)} for tool {base_tool_data.unique_name}"
                )
            self.connection_tool_executors[connection_key].append(tool_executor)

    async def get_realtime_tool_models(self, connection_key: str) -> list[RealtimeTool]:
        realtime_tool_models: list[RealtimeTool] = []
        for executor in self.connection_tool_executors[connection_key]:
            rt_tool_model = await executor.get_realtime_tool_model()
            realtime_tool_models.append(rt_tool_model)

        return realtime_tool_models

    async def execute(self, connection_key: str, tool_name: str, call_arguments: dict):
        for executor in self.connection_tool_executors[connection_key]:
            if executor.tool_name == tool_name:
                return await executor.execute(**call_arguments)

        return f"{tool_name} not found"
