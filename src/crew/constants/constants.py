import os


def _int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


# Knowledge search timeouts (seconds) per RAG type
DEFAULT_RAG_SEARCH_TIMEOUT = _int_env("DEFAULT_RAG_SEARCH_TIMEOUT", 20)
NAIVE_RAG_SEARCH_TIMEOUT = _int_env("NAIVE_RAG_SEARCH_TIMEOUT", 20)
GRAPH_RAG_SEARCH_TIMEOUT = _int_env("GRAPH_RAG_SEARCH_TIMEOUT", 600)
