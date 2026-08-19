import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    redis_host: str
    redis_port: int
    redis_password: str | None
    agent_request_stream: str
    agent_result_stream: str
    agent_consumer_group: str
    log_level: str
    agent_default_max_retries: int
    agent_default_max_iter: int
    agent_schema_max_retries: int
    sandbox_request_channel: str
    sandbox_result_channel: str
    agent_drop_unsupported_llm_params: bool
    agent_context_warning_ratio: float
    knowledge_search_request_channel: str
    knowledge_search_response_channel: str


def load_settings() -> Settings:
    return Settings(
        redis_host=os.environ.get("REDIS_HOST", "127.0.0.1"),
        redis_port=int(os.environ.get("REDIS_PORT", "6379")),
        redis_password=os.environ.get("REDIS_PASSWORD") or None,
        agent_request_stream=os.environ.get("AGENT_REQUEST_STREAM", "agent.requests"),
        agent_result_stream=os.environ.get("AGENT_RESULT_STREAM", "agent.results"),
        agent_consumer_group=os.environ.get("AGENT_CONSUMER_GROUP", "agent-executors"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        agent_default_max_retries=int(os.environ.get("AGENT_DEFAULT_MAX_RETRIES", "5")),
        agent_default_max_iter=int(os.environ.get("AGENT_DEFAULT_MAX_ITER", "25")),
        agent_schema_max_retries=int(os.environ.get("AGENT_SCHEMA_MAX_RETRIES", "2")),
        sandbox_request_channel=os.environ.get(
            "SANDBOX_REQUEST_CHANNEL", "code_exec_tasks"
        ),
        sandbox_result_channel=os.environ.get("SANDBOX_RESULT_CHANNEL", "code_results"),
        agent_drop_unsupported_llm_params=os.environ.get(
            "AGENT_DROP_UNSUPPORTED_LLM_PARAMS", "true"
        ).lower()
        in {"1", "true", "yes"},
        agent_context_warning_ratio=float(
            os.environ.get("AGENT_CONTEXT_WARNING_RATIO", "0.8")
        ),
        knowledge_search_request_channel=os.environ.get(
            "KNOWLEDGE_SEARCH_GET_CHANNEL", "knowledge:search:get"
        ),
        knowledge_search_response_channel=os.environ.get(
            "KNOWLEDGE_SEARCH_RESPONSE_CHANNEL", "knowledge:search:response"
        ),
    )
