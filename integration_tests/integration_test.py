import random
import uuid

import pytest

from loguru import logger
import requests

from utils.cleaning_utils import (
    delete_crews,
    delete_custom_tools,
    delete_graph,
    delete_session,
    validate_response,
)
from utils.knowledge_utils import knowledge_search
from utils.utils import (
    create_agent,
    create_conditional_edge,
    create_crew,
    create_crew_node,
    create_edge,
    create_end_node,
    create_graph,
    create_llm_config,
    create_mcp_tool,
    create_python_code_tool,
    create_python_node,
    create_start_node,
    create_task,
    get_headers,
    ensure_services_ready,
    get_python_code_tool_by_name,
    run_session,
    wait_for_results_sse,
)
from utils.variables import DJANGO_URL, TEST_TOOL_NAME


def test_create_and_run_session():
    ensure_services_ready()

    # Create configurations
    llm_id = get_llm_model()
    config_id = create_llm_config(llm_id=llm_id)
    config_id_2 = create_llm_config(llm_id=llm_id)

    author_crew_id = create_author_crew(config_id_2)
    user_crew_id = create_user_crew(config_id)

    graph_id = create_graph("Integration graph")

    author_crew_node_id = create_crew_node(
        crew_id=author_crew_id,
        node_name="author_crew_node",
        graph_id=graph_id,
        input_map={
            "user_id": "variables.user_name",
        },
        output_variable_path="variables.result",
    )
    user_crew_node_id = create_crew_node(
        crew_id=user_crew_id,
        node_name="user_crew_node",
        graph_id=graph_id,
        input_map={
            "user_id": "variables.user_id",
        },
        output_variable_path="variables",
    )
    start_node_id = create_start_node(graph_id=graph_id)
    hash_message_node_id = create_hash_message_python_node(graph_id=graph_id)
    option_1_node_id = create_option_1_python_node(graph_id=graph_id)
    option_2_node_id = create_option_2_python_node(graph_id=graph_id)
    end_node_id = create_end_node(graph_id=graph_id)
    create_edge(
        start_node_id=start_node_id, end_node_id=hash_message_node_id, graph=graph_id
    )
    create_edge(
        start_node_id=hash_message_node_id,
        end_node_id=user_crew_node_id,
        graph=graph_id,
    )
    create_user_name_conditional_edge(source_node_id=user_crew_node_id, graph=graph_id)
    create_edge(start_node_id=option_1_node_id, end_node_id=end_node_id, graph=graph_id)
    create_edge(
        start_node_id=option_2_node_id, end_node_id=author_crew_node_id, graph=graph_id
    )
    create_edge(
        start_node_id=author_crew_node_id, end_node_id=end_node_id, graph=graph_id
    )

    # Run sessions
    session1 = run_session(
        graph_id=graph_id,
        variables={"user_id": 14, "secret_message": "hello, crew"},
    )
    logger.success(f"Session with id {session1} created, yay!")

    wait_for_results_sse(session_id=session1)
    # wait_for_results_sse(session_id=session2)
    delete_session(session_id=session1)
    delete_crews(crew_ids_to_delete=[user_crew_id, author_crew_id])
    delete_graph(graph_id=graph_id)
    delete_custom_tools()


@pytest.mark.skip
@pytest.mark.asyncio
async def test_knowledges(collection_id, redis_service):
    """Knowledges created in 'collection_id' fixture"""
    test_query = "What makes MYM different from other logistics platforms?"

    # TODO: Knowledge status is unchangable for now.
    # Should rewrite this test after fulfilling knowledge status management.
    results = await knowledge_search(
        knowledge_collection_id=collection_id,
        query=test_query,
        redis_service=redis_service,
    )

    # Assertions
    assert results is not None
    assert isinstance(results, list)
    str_results = "\n".join(results)
    assert (
        "A secure and user-friendly platform designed for businesses of all sizes."
        in str_results
    )


def test_mcp_session(run_mcp_tool):
    # Create configurations
    llm_id = get_llm_model()
    config_id = create_llm_config(llm_id=llm_id)
    mcp_test_crew_id = create_mcp_test_crew(config_id)

    graph_id = create_graph("Integration graph2")
    mcp_crew_node_id = create_crew_node(
        crew_id=mcp_test_crew_id,
        node_name="mcp_test_crew_node",
        graph_id=graph_id,
        input_map={},
        output_variable_path="variables",
    )
    end_node_id = create_end_node(graph_id=graph_id)
    start_node_id = create_start_node(graph_id=graph_id)
    create_edge(
        start_node_id=start_node_id, end_node_id=mcp_crew_node_id, graph=graph_id
    )
    create_edge(start_node_id=mcp_crew_node_id, end_node_id=end_node_id, graph=graph_id)
    # Run sessions
    session_id = run_session(
        graph_id=graph_id,
        variables={},
    )
    logger.success(f"Session with id {session_id} created, yay!")

    # TODO: Fix getting BaseKnowledgeSearchMessage validation errors (src:knowledge:main::searching)
    wait_for_results_sse(session_id=session_id)
    delete_session(session_id=session_id)


def create_user_crew(llm_config_id):
    user_python_code_tool_id = create_user_python_code_tool()
    user_agent_id = create_user_agent(
        config_id=llm_config_id,
        python_code_tool_id_list=[user_python_code_tool_id],
    )
    user_crew_id = create_crew(name="USER CREW", agents=[user_agent_id])
    task_id, task_name = create_user_task(crew_id=user_crew_id, agent_id=user_agent_id)
    return user_crew_id


def create_author_crew(llm_config_id):
    author_agent_id = create_author_agent(config_id=llm_config_id)
    author_crew_id = create_crew(
        name="AUTHOR CREW",
        agents=[author_agent_id],
    )
    author_task_id, author_task_name = create_poem_task(
        crew_id=author_crew_id, agent_id=author_agent_id
    )
    return author_crew_id


def create_mcp_test_crew(llm_config_id):
    mcp_tool_id = create_mcp_tool("test-mcp", "http://fastmcp:8000/mcp", "test_tool_1")
    mcp_agent_id = create_mcp_agent(config_id=llm_config_id, mcp_tool_ids=[mcp_tool_id])
    mcp_crew_id = create_crew(
        name="MCP CREW",
        agents=[mcp_agent_id],
    )
    mcp_task_id, mcp_task_name = create_mcp_task(
        crew_id=mcp_crew_id, agent_id=mcp_agent_id
    )
    return mcp_crew_id


def create_poem_task(crew_id: int, agent_id: int) -> tuple:
    task_data = {
        "name": f"Test write poem task {random.randint(1, 100000)}",
        "instructions": "Write short rhyming poem about nature",
        "expected_output": "Short rhyming poem",
        "order": 1,
        "crew": crew_id,
        "agent": agent_id,
    }
    return create_task(**task_data)


def create_user_task(crew_id: int, agent_id: int) -> tuple:
    task_data = {
        "name": "user task",
        "instructions": "Get user name by user id {user_id}",
        "expected_output": "name",
        "order": 1,
        "crew": crew_id,
        "agent": agent_id,
        "output_model": {
            "type": "object",
            "title": "ArgumentsSchema",
            "properties": {
                "user_name": {
                    "type": "string",
                    "description": "Name of user",
                }
            },
        },
    }
    return create_task(**task_data)


def create_mcp_task(crew_id: int, agent_id: int) -> tuple:
    task_data = {
        "name": "user task",
        "instructions": "Use mcp tool to discover what it does. Argument is a name, Max",
        "expected_output": "tool result",
        "order": 1,
        "crew": crew_id,
        "agent": agent_id,
        "output_model": {
            "type": "object",
            "title": "ArgumentsSchema",
            "properties": {
                "user_name": {
                    "type": "string",
                    "description": "tool result",
                }
            },
        },
    }
    return create_task(**task_data)


def create_author_agent(
    config_id: int,
) -> int:
    agent_data = {
        "role": "poem writer",
        "goal": "write short poem",
        "backstory": "You are the agent who writes rhyming poems",
        "allow_delegation": False,
        "memory": False,
        "max_iter": 15,
        "llm_config": config_id,
        "fcm_llm_config": config_id,
    }
    return create_agent(**agent_data)


def create_user_agent(config_id: int, python_code_tool_id_list: list[int]) -> int:
    agent_data = {
        "role": "User Agent",
        "goal": "Persorm user related actions",
        "backstory": "Use tools to perform tasks",
        "allow_delegation": False,
        "memory": False,
        "tool_ids": [f"python-code-tool:{id_}" for id_ in python_code_tool_id_list],
        "max_iter": 15,
        "llm_config": config_id,
        "fcm_llm_config": config_id,
    }
    return create_agent(**agent_data)


def create_mcp_agent(config_id: int, mcp_tool_ids: list[int]):
    agent_data = {
        "role": "User Agent",
        "goal": "Persorm user related actions",
        "backstory": "Use tools to perform tasks",
        "allow_delegation": False,
        "memory": False,
        "tool_ids": [f"mcp-tool:{id_}" for id_ in mcp_tool_ids],
        "max_iter": 15,
        "llm_config": config_id,
        "fcm_llm_config": config_id,
    }
    return create_agent(**agent_data)


def create_user_python_code_tool() -> int:
    code = """
def main(user_id: int):
    ids = {
        14: "Artur",
        2: "Max",
        36: "Igor",
    }
    return ids.get(user_id, "Not found")
"""

    args_schema = {
        "type": "object",
        "title": "ArgumentsSchema",
        "properties": {
            "user_id": {"type": "integer", "description": "id of user"},
        },
    }

    tool_data = {
        "name": TEST_TOOL_NAME,
        "description": "Get user name from id",
        "code": code,
        "entrypoint": "main",
        "libraries": ["requests"],
        "global_kwargs": {},
        "args_schema": args_schema,
    }
    tool = get_python_code_tool_by_name(tool_data["name"])
    if tool is not None:
        tool_data["name"] = f"{tool_data['name']}_{str(uuid.uuid4())}"
    tool = create_python_code_tool(**tool_data)
    return tool


def create_hash_message_python_node(graph_id: int) -> int:
    code = """
import hashlib
def main(user_id: int, secret_message: str):
    m = hashlib.sha256(secret_message.encode()).hexdigest()
    return {'hash': m, 'user_id': user_id}
"""

    python_node_data = {
        "libraries": [],
        "code": code,
        "entrypoint": "main",
        "global_kwargs": {},
        "node_name": "hash_message",
        "graph": graph_id,
        "input_map": {
            "user_id": "variables.user_id",
            "secret_message": "variables.secret_message",
        },
        "output_variable_path": "variables",
    }

    return create_python_node(**python_node_data)


def create_option_1_python_node(graph_id: int) -> int:
    code = """
def main(*args, **kwargs):
    return {'query': f"Famous {kwargs.get('user_name')}s in the world"}
"""

    python_node_data = {
        "libraries": [],
        "code": code,
        "entrypoint": "main",
        "global_kwargs": {},
        "node_name": "option_1",
        "graph": graph_id,
        "input_map": {
            "user_name": "variables.user_name",
        },
        "output_variable_path": "variables",
    }
    return create_python_node(**python_node_data)


def create_option_2_python_node(graph_id: int) -> int:
    code = """
def main(*args, **kwargs):
    return {'result': "option_2"}
"""

    python_node_data = {
        "libraries": [],
        "code": code,
        "entrypoint": "main",
        "global_kwargs": {},
        "node_name": "option_2",
        "graph": graph_id,
        "input_map": {
            "user_name": "variables.user_name",
        },
        "output_variable_path": "variables",
    }

    return create_python_node(**python_node_data)


def create_user_name_conditional_edge(source_node_id: int, graph: int):
    code = """
def main():
    user_name = state["variables"]["user_name"]

    if user_name == "Artur":
        return "option_1"
    else:
        return "option_2"
"""

    conditional_edge_data = {
        "source_node_id": source_node_id,
        "graph": graph,
        "code": code,
    }
    return create_conditional_edge(**conditional_edge_data)


def get_llm_model(name: str = "gpt-4o-mini"):
    llm_model_response = requests.get(
        f"{DJANGO_URL}/llm-models?name={name}", headers=get_headers()
    )
    llm_model = None
    if llm_model_response.ok:
        results = llm_model_response.json()["results"]
        if len(results) > 0:
            llm_model = results[0]
    return llm_model["id"]
