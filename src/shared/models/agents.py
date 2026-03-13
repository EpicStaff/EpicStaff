from pydantic import BaseModel
from enum import Enum
from typing import Literal, List, Any
from pydantic import ConfigDict
from .ai_providers import LLMData, EmbedderData
from .tools import ConfiguredToolData, PythonCodeToolData, BaseToolData
from .knowledge import RagSearchConfig


class AgentData(BaseModel):
    id: int
    role: str
    goal: str
    backstory: str
    tool_id_list: list[int] = []
    tool_unique_name_list: list[str] = []
    python_code_tool_id_list: list[int] = []
    max_iter: int
    max_rpm: int
    max_execution_time: int
    memory: bool
    allow_delegation: bool
    cache: bool
    allow_code_execution: bool
    max_retry_limit: int
    llm: LLMData | None = None
    embedder: EmbedderData | None = None
    function_calling_llm: LLMData | None
    knowledge_collection_id: int | None

    rag_type_id: str | None = None
    rag_search_config: RagSearchConfig | None = None

    model_config = ConfigDict(from_attributes=True)


class RealtimeAgentData(BaseModel):
    role: str
    goal: str
    backstory: str
    knowledge_collection_id: int | None
    llm: LLMData | None = None
    memory: bool
    tools: list[ConfiguredToolData] = []
    python_code_tools: list[PythonCodeToolData] = []
    connection_key: str

    model_config = ConfigDict(from_attributes=True)


class RealtimeAgentChatData(BaseModel):
    role: str
    goal: str
    backstory: str
    knowledge_collection_id: int | None
    rag_type_id: str | None = None
    rag_search_config: RagSearchConfig | None = None
    llm: LLMData | None = None
    rt_model_name: str
    rt_api_key: str
    transcript_model_name: str
    transcript_api_key: str
    temperature: float | None
    memory: bool
    tools: list[BaseToolData] = []
    connection_key: str
    wake_word: str | None
    stop_prompt: str | None
    language: str | None
    voice_recognition_prompt: str | None
    voice: str
    input_audio_format: Literal["pcm16", "g711_ulaw", "g711_alaw"] = "pcm16"
    output_audio_format: Literal["pcm16", "g711_ulaw", "g711_alaw"] = "pcm16"


class CrewData(BaseModel):
    class Process(str, Enum):
        sequential = "sequential"
        hierarhical = "hierarchical"

    agents: List[AgentData]
    id: int
    name: str
    process: Process = Process.sequential
    memory: bool = False
    tasks: List["TaskData"] | None
    config: dict[str, Any] | None
    max_rpm: int
    cache: bool
    full_output: bool | None
    planning: bool | None
    embedder: EmbedderData | None
    memory_llm: LLMData | None = None
    manager_llm: LLMData | None
    planning_llm: LLMData | None
    tools: List[BaseToolData] = []

    python_code_tools: list[PythonCodeToolData] = []
    knowledge_collection_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskData(BaseModel):
    id: int
    name: str
    agent_id: int
    instructions: str
    knowledge_query: str | None = None
    expected_output: str
    order: int = 1
    human_input: bool
    async_execution: bool
    config: dict | None
    output_model: dict | None
    tool_unique_name_list: list[str] = []
    task_context_id_list: list[int] = []
    task_tool_id_list: list[int] = []
    task_python_code_tool_id_list: list[int] = []

    model_config = ConfigDict(from_attributes=True)


class TaskMessageData(BaseModel):
    crew_id: int
    task_id: int
    description: str
    raw: str
    name: str
    expected_output: str
    agent: str

    model_config = ConfigDict(from_attributes=True)
