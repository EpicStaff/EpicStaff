"""
Integration tests for Python code tools with the new `variables` format (EST-1529).

Tests:
  1. test_user_input_default        — user_input variable uses default_value (no config override)
  2. test_user_input_config_override — user_input variable overridden via PythonCodeToolConfig
  3. test_multiple_agent_inputs     — multiple agent_input variables, all supplied by LLM
  4. test_mixed_uses_default        — mixed variable: agent doesn't set it, default_value used
  5. test_mixed_agent_required_when_no_default — mixed without default: agent sees it as required
  6. test_nested_object_variable    — agent_input of type object with nested properties
  7. test_array_variable            — agent_input of type array with items schema
"""

import json
import os
import time
import uuid

import requests
from loguru import logger
from sseclient import SSEClient

from utils.variables import DJANGO_URL, rhost

MAX_WAIT_SSE_SECONDS = 180


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _make_session() -> requests.Session:
    """Return a requests.Session with a valid Bearer token."""
    username = os.environ.get("DJANGO_TEST_USERNAME", "admin")
    password = os.environ.get("DJANGO_TEST_PASSWORD", "admin123!")

    s = requests.Session()
    s.headers.update({"Host": rhost})

    r = s.post(f"{DJANGO_URL}/auth/token/", json={"username": username, "password": password})
    if r.ok:
        s.headers["Authorization"] = f"Bearer {r.json()['access']}"
        return s

    r = s.post(
        f"{DJANGO_URL}/auth/first-setup/",
        json={"username": username, "password": password},
    )
    if r.ok:
        s.headers["Authorization"] = f"Bearer {r.json()['access']}"
        return s

    raise RuntimeError(
        f"Cannot authenticate as '{username}': {r.status_code} {r.text[:200]}"
    )


# ---------------------------------------------------------------------------
# Thin REST helpers
# ---------------------------------------------------------------------------

def _j(response: requests.Response) -> dict:
    response.raise_for_status()
    return response.json()


def _session_status(session_id: int, s: requests.Session) -> str:
    return _j(s.get(f"{DJANGO_URL}/sessions/{session_id}/")).get("status", "")


def _wait_for_session(session_id: int, s: requests.Session) -> dict:
    """Stream SSE events until graph_end; fast-fail on session error."""
    url = f"{DJANGO_URL}/run-session/subscribe/{session_id}/"
    start = time.time()
    STATUS_POLL_INTERVAL = 15

    logger.info(f"SSE: subscribing to session {session_id}")

    while time.time() - start < MAX_WAIT_SSE_SECONDS:
        status = _session_status(session_id, s)
        if status == "error":
            raise RuntimeError(f"Session {session_id} failed (status='error')")

        try:
            for event in SSEClient(url, session=s, timeout=(10, STATUS_POLL_INTERVAL)):
                if time.time() - start > MAX_WAIT_SSE_SECONDS:
                    raise TimeoutError(f"SSE timed out after {MAX_WAIT_SSE_SECONDS}s")

                if event.event != "messages":
                    continue

                data = json.loads(event.data)
                msg = data.get("message_data", {})

                if msg.get("message_type") == "graph_end":
                    result = msg.get("end_node_result") or {}
                    logger.info(f"graph_end: {result}")
                    return result

                logger.debug(f"SSE event: {msg.get('message_type')}")

        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            pass

    raise TimeoutError(f"Session {session_id} did not complete in {MAX_WAIT_SSE_SECONDS}s")


# ---------------------------------------------------------------------------
# Shared session runner
# ---------------------------------------------------------------------------

def _get_llm_config_id(s: requests.Session) -> int:
    llm_id = _j(s.get(f"{DJANGO_URL}/llm-models?name=gpt-4o-mini"))["results"][0]["id"]
    return _j(
        s.post(
            f"{DJANGO_URL}/llm-configs/",
            json={
                "custom_name": f"vars-test-{uuid.uuid4().hex[:6]}",
                "model": llm_id,
                "temperature": 0,
                "api_key": os.environ.get("OPENAI_KEY"),
            },
        )
    )["id"]


def _run_tool_session(
    s: requests.Session,
    *,
    tool_id: int,
    task_instructions: str,
    tool_id_str: str | None = None,
    llm_config_id: int,
) -> dict:
    """
    Wire tool_id into a minimal one-crew graph, run a session, return end_node_result.
    tool_id_str overrides the tool reference string (e.g. "python-code-tool-config:42").
    """
    tool_ref = tool_id_str or f"python-code-tool:{tool_id}"

    agent_id = crew_id = task_id = graph_id = session_id = None
    try:
        agent_id = _j(
            s.post(
                f"{DJANGO_URL}/agents/",
                json={
                    "role": "Tool Tester",
                    "goal": "Use the provided tool as instructed",
                    "backstory": "You execute tools to test their behaviour.",
                    "allow_delegation": False,
                    "memory": False,
                    "tool_ids": [tool_ref],
                    "max_iter": 5,
                    "llm_config": llm_config_id,
                    "fcm_llm_config": llm_config_id,
                },
            )
        )["id"]

        crew_id = _j(
            s.post(
                f"{DJANGO_URL}/crews/",
                json={"name": f"test-crew-{uuid.uuid4().hex[:6]}", "agents": [agent_id]},
            )
        )["id"]

        task_id = _j(
            s.post(
                f"{DJANGO_URL}/tasks/",
                json={
                    "name": "test task",
                    "instructions": task_instructions,
                    "expected_output": "Result string from the tool",
                    "order": 1,
                    "crew": crew_id,
                    "agent": agent_id,
                },
            )
        )["id"]

        graph_id = _j(
            s.post(
                f"{DJANGO_URL}/graphs/",
                json={
                    "name": f"test-graph-{uuid.uuid4().hex[:6]}",
                    "description": "Variables integration test",
                },
            )
        )["id"]

        start_node_id = _j(
            s.post(f"{DJANGO_URL}/startnodes/", json={"graph": graph_id, "variables": {}})
        )["id"]

        crew_node_id = _j(
            s.post(
                f"{DJANGO_URL}/crewnodes/",
                json={
                    "crew_id": crew_id,
                    "node_name": "test_crew_node",
                    "graph": graph_id,
                    "input_map": {},
                    "output_variable_path": "variables.result",
                },
            )
        )["id"]

        end_node_id = _j(
            s.post(
                f"{DJANGO_URL}/endnodes/",
                json={"graph": graph_id, "output_map": {"result": "variables.result"}},
            )
        )["id"]

        s.post(
            f"{DJANGO_URL}/edges/",
            json={"start_node_id": start_node_id, "end_node_id": crew_node_id, "graph": graph_id},
        ).raise_for_status()
        s.post(
            f"{DJANGO_URL}/edges/",
            json={"start_node_id": crew_node_id, "end_node_id": end_node_id, "graph": graph_id},
        ).raise_for_status()

        session_id = _j(
            s.post(f"{DJANGO_URL}/run-session/", json={"graph_id": graph_id, "variables": {}})
        )["session_id"]
        logger.success(f"Session {session_id} started")

        return _wait_for_session(session_id, s)

    finally:
        for url in filter(None, [
            f"{DJANGO_URL}/sessions/{session_id}/" if session_id else None,
            f"{DJANGO_URL}/tasks/{task_id}/" if task_id else None,
            f"{DJANGO_URL}/agents/{agent_id}/" if agent_id else None,
            f"{DJANGO_URL}/crews/{crew_id}/" if crew_id else None,
            f"{DJANGO_URL}/graphs/{graph_id}/" if graph_id else None,
        ]):
            try:
                s.delete(url)
            except Exception as exc:
                logger.warning(f"Cleanup failed for {url}: {exc}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_user_input_default():
    """
    user_input variable: default_value from the tool definition is injected
    server-side without any PythonCodeToolConfig override.
    Tool: item (agent_input) + suffix (user_input, default="_done")
    Expected: LLM calls tool with item="hello", server injects suffix="_done" → "hello_done"
    """
    s = _make_session()
    tool_id = config_id = None
    try:
        config_id = _get_llm_config_id(s)

        code = """
def main(**kwargs):
    item = kwargs.get("item", "")
    suffix = kwargs.get("suffix", "")
    return f"{item}{suffix}"
"""
        tool_id = _j(
            s.post(
                f"{DJANGO_URL}/python-code-tool/",
                json={
                    "name": f"UserInputDefault_{uuid.uuid4().hex[:8]}",
                    "description": (
                        "Echo the provided item with an appended suffix. "
                        "Call this tool when asked to process or echo an item."
                    ),
                    "python_code": {"code": code, "entrypoint": "main", "libraries": [], "global_kwargs": {}},
                    "variables": [
                        {
                            "name": "item",
                            "type": "string",
                            "description": "The item string to echo",
                            "input_type": "agent_input",
                            "required": True,
                            "default_value": None,
                        },
                        {
                            "name": "suffix",
                            "type": "string",
                            "description": "Suffix appended server-side",
                            "input_type": "user_input",
                            "required": False,
                            "default_value": "_done",
                        },
                    ],
                },
            )
        )["id"]
        logger.info(f"Created tool id={tool_id}")

        result = _run_tool_session(
            s,
            tool_id=tool_id,
            task_instructions='Use the echo tool to process the item "hello".',
            llm_config_id=config_id,
        )
        logger.success(f"Result: {result}")

    finally:
        for url in filter(None, [
            f"{DJANGO_URL}/python-code-tool/{tool_id}/" if tool_id else None,
            f"{DJANGO_URL}/llm-configs/{config_id}/" if config_id else None,
        ]):
            try:
                s.delete(url)
            except Exception as exc:
                logger.warning(f"Cleanup failed for {url}: {exc}")


def test_user_input_config_override():
    """
    user_input variable: PythonCodeToolConfig overrides the tool's default_value.
    Tool: item (agent_input) + suffix (user_input, default="_done")
    Config sets suffix="_overridden"
    Expected: server injects suffix="_overridden" → "hello_overridden"
    """
    s = _make_session()
    tool_id = tool_config_id = config_id = None
    try:
        config_id = _get_llm_config_id(s)

        code = """
def main(**kwargs):
    item = kwargs.get("item", "")
    suffix = kwargs.get("suffix", "")
    return f"{item}{suffix}"
"""
        tool_id = _j(
            s.post(
                f"{DJANGO_URL}/python-code-tool/",
                json={
                    "name": f"UserInputOverride_{uuid.uuid4().hex[:8]}",
                    "description": (
                        "Echo the provided item with an appended suffix. "
                        "Call this tool when asked to process or echo an item."
                    ),
                    "python_code": {"code": code, "entrypoint": "main", "libraries": [], "global_kwargs": {}},
                    "variables": [
                        {
                            "name": "item",
                            "type": "string",
                            "description": "The item string to echo",
                            "input_type": "agent_input",
                            "required": True,
                            "default_value": None,
                        },
                        {
                            "name": "suffix",
                            "type": "string",
                            "description": "Suffix appended server-side",
                            "input_type": "user_input",
                            "required": False,
                            "default_value": "_done",
                        },
                    ],
                },
            )
        )["id"]
        logger.info(f"Created tool id={tool_id}")

        tool_config_id = _j(
            s.post(
                f"{DJANGO_URL}/python-code-tool-configs/",
                json={
                    "name": f"override-config-{uuid.uuid4().hex[:6]}",
                    "tool": tool_id,
                    "configuration": {"suffix": "_overridden"},
                },
            )
        )["id"]
        logger.info(f"Created tool config id={tool_config_id}")

        result = _run_tool_session(
            s,
            tool_id=tool_id,
            task_instructions='Use the echo tool to process the item "hello".',
            tool_id_str=f"python-code-tool-config:{tool_config_id}",
            llm_config_id=config_id,
        )
        logger.success(f"Result: {result}")

    finally:
        for url in filter(None, [
            f"{DJANGO_URL}/python-code-tool-configs/{tool_config_id}/" if tool_config_id else None,
            f"{DJANGO_URL}/python-code-tool/{tool_id}/" if tool_id else None,
            f"{DJANGO_URL}/llm-configs/{config_id}/" if config_id else None,
        ]):
            try:
                s.delete(url)
            except Exception as exc:
                logger.warning(f"Cleanup failed for {url}: {exc}")


def test_multiple_agent_inputs():
    """
    Multiple agent_input variables: LLM must supply all required fields.
    Tool: first_name (agent_input, required) + last_name (agent_input, required)
    Expected: LLM calls tool with both values → "John Doe"
    """
    s = _make_session()
    tool_id = config_id = None
    try:
        config_id = _get_llm_config_id(s)

        code = """
def main(**kwargs):
    first = kwargs.get("first_name", "")
    last = kwargs.get("last_name", "")
    return f"{first} {last}"
"""
        tool_id = _j(
            s.post(
                f"{DJANGO_URL}/python-code-tool/",
                json={
                    "name": f"MultiAgentInput_{uuid.uuid4().hex[:8]}",
                    "description": (
                        "Combine a first name and last name into a full name. "
                        "Call this tool when asked to combine or format a person's name."
                    ),
                    "python_code": {"code": code, "entrypoint": "main", "libraries": [], "global_kwargs": {}},
                    "variables": [
                        {
                            "name": "first_name",
                            "type": "string",
                            "description": "The person's first name",
                            "input_type": "agent_input",
                            "required": True,
                            "default_value": None,
                        },
                        {
                            "name": "last_name",
                            "type": "string",
                            "description": "The person's last name",
                            "input_type": "agent_input",
                            "required": True,
                            "default_value": None,
                        },
                    ],
                },
            )
        )["id"]
        logger.info(f"Created tool id={tool_id}")

        result = _run_tool_session(
            s,
            tool_id=tool_id,
            task_instructions=(
                'Use the name combination tool to combine the first name "John" '
                'and last name "Doe" into a full name.'
            ),
            llm_config_id=config_id,
        )
        logger.success(f"Result: {result}")

    finally:
        for url in filter(None, [
            f"{DJANGO_URL}/python-code-tool/{tool_id}/" if tool_id else None,
            f"{DJANGO_URL}/llm-configs/{config_id}/" if config_id else None,
        ]):
            try:
                s.delete(url)
            except Exception as exc:
                logger.warning(f"Cleanup failed for {url}: {exc}")


def test_mixed_uses_default():
    """
    mixed variable: agent doesn't override it → server-side default_value is used.
    Tool: item (agent_input, required) + count (mixed, integer, default=3)
    Task says nothing about count → agent calls tool with only item.
    Expected: session completes; count=3 used by code internally.
    """
    s = _make_session()
    tool_id = config_id = None
    try:
        config_id = _get_llm_config_id(s)

        code = """
def main(**kwargs):
    item = kwargs.get("item", "")
    count = kwargs.get("count", 1)
    return f"{item}*{count}"
"""
        tool_id = _j(
            s.post(
                f"{DJANGO_URL}/python-code-tool/",
                json={
                    "name": f"MixedDefault_{uuid.uuid4().hex[:8]}",
                    "description": (
                        "Repeat an item a given number of times. "
                        "Call this tool when asked to repeat or multiply an item. "
                        "The count parameter is optional."
                    ),
                    "python_code": {"code": code, "entrypoint": "main", "libraries": [], "global_kwargs": {}},
                    "variables": [
                        {
                            "name": "item",
                            "type": "string",
                            "description": "The item to repeat",
                            "input_type": "agent_input",
                            "required": True,
                            "default_value": None,
                        },
                        {
                            "name": "count",
                            "type": "integer",
                            "description": "How many times to repeat (optional, defaults to 3)",
                            "input_type": "mixed",
                            "required": False,
                            "default_value": 3,
                        },
                    ],
                },
            )
        )["id"]
        logger.info(f"Created tool id={tool_id}")

        result = _run_tool_session(
            s,
            tool_id=tool_id,
            task_instructions='Use the repeat tool to process the item "ping". Do not specify count.',
            llm_config_id=config_id,
        )
        logger.success(f"Result: {result}")

    finally:
        for url in filter(None, [
            f"{DJANGO_URL}/python-code-tool/{tool_id}/" if tool_id else None,
            f"{DJANGO_URL}/llm-configs/{config_id}/" if config_id else None,
        ]):
            try:
                s.delete(url)
            except Exception as exc:
                logger.warning(f"Cleanup failed for {url}: {exc}")


def test_mixed_agent_required_when_no_default():
    """
    mixed variable without default_value → no user/server value exists.
    Agent sees it in schema as required and must supply it.
    Tool: item (agent_input) + count (mixed, no default)
    Expected: agent passes count, session completes.
    """
    s = _make_session()
    tool_id = config_id = None
    try:
        config_id = _get_llm_config_id(s)

        code = """
def main(**kwargs):
    item = kwargs.get("item", "")
    count = kwargs.get("count", 1)
    return f"{item}*{count}"
"""
        tool_id = _j(
            s.post(
                f"{DJANGO_URL}/python-code-tool/",
                json={
                    "name": f"MixedNoDefault_{uuid.uuid4().hex[:8]}",
                    "description": (
                        "Repeat an item a given number of times. "
                        "Call this tool when asked to repeat or multiply an item. "
                        "You must provide both item and count."
                    ),
                    "python_code": {"code": code, "entrypoint": "main", "libraries": [], "global_kwargs": {}},
                    "variables": [
                        {
                            "name": "item",
                            "type": "string",
                            "description": "The item to repeat",
                            "input_type": "agent_input",
                            "required": True,
                            "default_value": None,
                        },
                        {
                            "name": "count",
                            "type": "integer",
                            "description": "How many times to repeat",
                            "input_type": "mixed",
                            "required": False,
                            "default_value": None,  # no user value → agent must supply
                        },
                    ],
                },
            )
        )["id"]
        logger.info(f"Created tool id={tool_id}")

        result = _run_tool_session(
            s,
            tool_id=tool_id,
            task_instructions=(
                'Use the repeat tool to process the item "ping" 5 times.'
            ),
            llm_config_id=config_id,
        )
        logger.success(f"Result: {result}")

    finally:
        for url in filter(None, [
            f"{DJANGO_URL}/python-code-tool/{tool_id}/" if tool_id else None,
            f"{DJANGO_URL}/llm-configs/{config_id}/" if config_id else None,
        ]):
            try:
                s.delete(url)
            except Exception as exc:
                logger.warning(f"Cleanup failed for {url}: {exc}")


def test_nested_object_variable():
    """
    agent_input variable of type "object" with nested properties.
    Tool: person (object, required) with properties first_name + last_name (both strings).
    LLM must call tool with {"first_name": "Alice", "last_name": "Smith"}.
    Expected: session completes and tool returns "Alice Smith".
    """
    s = _make_session()
    tool_id = config_id = None
    try:
        config_id = _get_llm_config_id(s)

        code = """
def main(**kwargs):
    person = kwargs.get("person", {})
    if isinstance(person, str):
        import json
        person = json.loads(person)
    first = person.get("first_name", "")
    last = person.get("last_name", "")
    return f"{first} {last}"
"""
        tool_id = _j(
            s.post(
                f"{DJANGO_URL}/python-code-tool/",
                json={
                    "name": f"NestedObject_{uuid.uuid4().hex[:8]}",
                    "description": (
                        "Format a full name from a person object containing first_name and last_name. "
                        "Call this tool when asked to format or display a person's full name."
                    ),
                    "python_code": {"code": code, "entrypoint": "main", "libraries": [], "global_kwargs": {}},
                    "variables": [
                        {
                            "name": "person",
                            "type": "object",
                            "description": "Person object with first_name and last_name fields",
                            "input_type": "agent_input",
                            "required": True,
                            "default_value": None,
                            "properties": {
                                "first_name": {"type": "string", "description": "First name"},
                                "last_name": {"type": "string", "description": "Last name"},
                            },
                            "required_properties": ["first_name", "last_name"],
                        },
                    ],
                },
            )
        )["id"]
        logger.info(f"Created tool id={tool_id}")

        result = _run_tool_session(
            s,
            tool_id=tool_id,
            task_instructions=(
                'Use the name formatting tool with person={"first_name": "Alice", "last_name": "Smith"} '
                "to produce the full name."
            ),
            llm_config_id=config_id,
        )
        logger.success(f"Result: {result}")

    finally:
        for url in filter(None, [
            f"{DJANGO_URL}/python-code-tool/{tool_id}/" if tool_id else None,
            f"{DJANGO_URL}/llm-configs/{config_id}/" if config_id else None,
        ]):
            try:
                s.delete(url)
            except Exception as exc:
                logger.warning(f"Cleanup failed for {url}: {exc}")


def test_array_variable():
    """
    agent_input variable of type "array" with items schema (array of strings).
    Tool: tags (array of strings, required).
    LLM must call tool with ["python", "ai", "tools"].
    Expected: session completes and tool returns "python, ai, tools".
    """
    s = _make_session()
    tool_id = config_id = None
    try:
        config_id = _get_llm_config_id(s)

        code = """
def main(**kwargs):
    tags = kwargs.get("tags", [])
    if isinstance(tags, str):
        import json
        tags = json.loads(tags)
    return ", ".join(str(t) for t in tags)
"""
        tool_id = _j(
            s.post(
                f"{DJANGO_URL}/python-code-tool/",
                json={
                    "name": f"ArrayTags_{uuid.uuid4().hex[:8]}",
                    "description": (
                        "Join a list of tags into a comma-separated string. "
                        "Call this tool when asked to format or combine a list of tags."
                    ),
                    "python_code": {"code": code, "entrypoint": "main", "libraries": [], "global_kwargs": {}},
                    "variables": [
                        {
                            "name": "tags",
                            "type": "array",
                            "description": "List of tag strings to join",
                            "input_type": "agent_input",
                            "required": True,
                            "default_value": None,
                            "items": {"type": "string"},
                        },
                    ],
                },
            )
        )["id"]
        logger.info(f"Created tool id={tool_id}")

        result = _run_tool_session(
            s,
            tool_id=tool_id,
            task_instructions=(
                'Use the tag formatting tool with tags=["python", "ai", "tools"] '
                "to produce a comma-separated string."
            ),
            llm_config_id=config_id,
        )
        logger.success(f"Result: {result}")

    finally:
        for url in filter(None, [
            f"{DJANGO_URL}/python-code-tool/{tool_id}/" if tool_id else None,
            f"{DJANGO_URL}/llm-configs/{config_id}/" if config_id else None,
        ]):
            try:
                s.delete(url)
            except Exception as exc:
                logger.warning(f"Cleanup failed for {url}: {exc}")
