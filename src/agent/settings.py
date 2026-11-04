from pathlib import Path

from shared.envtools import Env

BASE_DIR = Path(__file__).resolve().parent


def whole_seconds_at_least_one(variable: str, seconds: float | None) -> int:
    """Validate a duration used as a Redis EXPIRE, which only takes whole seconds.

    ``None`` would crash on ``int()`` and anything under one second truncates
    to ``EXPIRE key 0``, which deletes the key immediately.
    """
    if seconds is None or seconds < 1:
        raise ValueError(f"{variable} must be a duration of at least 1s, got {seconds!r}")
    return int(seconds)


def positive_seconds(variable: str, seconds: float | None) -> float:
    """Validate a duration that must be above zero (``None`` is the ``none`` env value)."""
    if seconds is None or seconds <= 0:
        raise ValueError(f"{variable} must be a duration above 0s, got {seconds!r}")
    return seconds


env = Env()
if not env.bool("RUN_IN_DOCKER", False):
    env.read_env(BASE_DIR / "../.env")

LOG_LEVEL = env.log_level("AGENT_LOG_LEVEL", allowed=env.LOG_LEVELS_WITH_BENCH)

REDIS_HOST = env.str("REDIS_HOST")
REDIS_PORT = env.int("REDIS_PORT")
REDIS_USER = env.str("REDIS_USER")
REDIS_PASSWORD = env.str("REDIS_PASSWORD")

AGENT_REQUEST_STREAM = env.str("AGENT_REQUEST_STREAM")
# Prefix, not a stream: each run publishes to "<prefix>:<correlation_id>".
AGENT_RESULT_STREAM = env.str("AGENT_RESULT_STREAM")
AGENT_RESULT_STREAM_TTL = whole_seconds_at_least_one(
    "AGENT_RESULT_STREAM_TTL", env.time("AGENT_RESULT_STREAM_TTL")
)
AGENT_CONSUMER_GROUP = env.str("AGENT_CONSUMER_GROUP")
AGENT_MAX_CONCURRENT_RUNS = env.int("AGENT_MAX_CONCURRENT_RUNS")
if AGENT_MAX_CONCURRENT_RUNS < 1:
    raise ValueError(
        f"AGENT_MAX_CONCURRENT_RUNS must be at least 1, got {AGENT_MAX_CONCURRENT_RUNS}"
    )
AGENT_REDIS_READ_RETRY_INITIAL_DELAY = positive_seconds(
    "AGENT_REDIS_READ_RETRY_INITIAL_DELAY", env.time("AGENT_REDIS_READ_RETRY_INITIAL_DELAY")
)
AGENT_REDIS_READ_RETRY_MAX_DELAY = positive_seconds(
    "AGENT_REDIS_READ_RETRY_MAX_DELAY", env.time("AGENT_REDIS_READ_RETRY_MAX_DELAY")
)
if AGENT_REDIS_READ_RETRY_MAX_DELAY < AGENT_REDIS_READ_RETRY_INITIAL_DELAY:
    raise ValueError(
        "AGENT_REDIS_READ_RETRY_MAX_DELAY must be at least AGENT_REDIS_READ_RETRY_INITIAL_DELAY, "
        f"got {AGENT_REDIS_READ_RETRY_MAX_DELAY} < {AGENT_REDIS_READ_RETRY_INITIAL_DELAY}"
    )

AGENT_DEFAULT_MAX_RETRIES = env.int("AGENT_DEFAULT_MAX_RETRIES")
AGENT_DEFAULT_MAX_ITER = env.int("AGENT_DEFAULT_MAX_ITER")
AGENT_SCHEMA_MAX_RETRIES = env.int("AGENT_SCHEMA_MAX_RETRIES")

CODE_EXEC_CHANNEL = env.str("CODE_EXEC_CHANNEL")
CODE_RESULT_CHANNEL = env.str("CODE_RESULT_CHANNEL")

SANDBOX_HOST = env.str("SANDBOX_HOST")
SANDBOX_PORT = env.int("SANDBOX_PORT")
AGENT_SANDBOX_TIMEOUT = env.time("AGENT_SANDBOX_TIMEOUT")
# Total time a submit keeps retrying a sandbox that is full or unreachable.
SANDBOX_QUEUE_TIMEOUT = env.time("SANDBOX_QUEUE_TIMEOUT")
# Backstop for the wait on a python-code tool result; a lost execution is caught
# sooner by the status checks. None means "wait while the sandbox has it".
AGENT_CODE_RESULT_TIMEOUT = env.time("AGENT_CODE_RESULT_TIMEOUT")

AGENT_DROP_UNSUPPORTED_LLM_PARAMS = env.bool("AGENT_DROP_UNSUPPORTED_LLM_PARAMS")
AGENT_CONTEXT_WARNING_RATIO = env.float("AGENT_CONTEXT_WARNING_RATIO")
AGENT_MCP_DESCRIBE_CACHE_TTL = positive_seconds(
    "AGENT_MCP_DESCRIBE_CACHE_TTL", env.time("AGENT_MCP_DESCRIBE_CACHE_TTL")
)

KNOWLEDGE_SEARCH_REQUEST_CHANNEL = env.str("KNOWLEDGE_SEARCH_REQUEST_CHANNEL")
KNOWLEDGE_SEARCH_RESPONSE_CHANNEL = env.str("KNOWLEDGE_SEARCH_RESPONSE_CHANNEL")
NAIVE_RAG_SEARCH_TIMEOUT = env.time("NAIVE_RAG_SEARCH_TIMEOUT")
GRAPH_RAG_SEARCH_TIMEOUT = env.time("GRAPH_RAG_SEARCH_TIMEOUT")

KNOWLEDGE_HOST = env.str("KNOWLEDGE_HOST")
KNOWLEDGE_PORT = env.str("KNOWLEDGE_PORT")

KNOWLEDGE_BASE_URL = f"http://{KNOWLEDGE_HOST}:{KNOWLEDGE_PORT}"
