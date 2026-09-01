from pydantic import BaseModel
from typing import Literal
from pydantic import ConfigDict, Field
from .ai_providers import LLMData, EmbedderData
from .tools import BaseToolData
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
    rag_embedder_api_key: str | None = None
    rag_embedder_api_key_secret_id: int | None = Field(default=None, exclude=True)

    model_config = ConfigDict(from_attributes=True)


class RealtimeAgentChatData(BaseModel):
    role: str
    goal: str
    backstory: str
    org_id: int
    user_id: int | None = None
    knowledge_collection_id: int | None
    rag_type_id: str | None = None
    rag_search_config: RagSearchConfig | None = None
    rag_embedder_api_key: str | None = None
    rag_embedder_api_key_secret_id: int | None = Field(default=None, exclude=True)
    llm: LLMData | None = None
    rt_model_name: str
    rt_api_key: str | None = None
    rt_api_key_secret_id: int | None = Field(default=None, exclude=True)
    transcript_model_name: str | None = None
    transcript_api_key: str | None = None
    transcript_api_key_secret_id: int | None = Field(default=None, exclude=True)
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
    rt_provider: str = "openai"  # "openai" | "elevenlabs" | "gemini"
    model_config = ConfigDict(from_attributes=True)
