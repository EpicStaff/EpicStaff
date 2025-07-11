from time import sleep

import pytest

from utils.utils import *
from utils.knowledge_utils import *
import uuid
from loguru import logger

from utils.variables import MANAGER_URL


def test_create_and_run_session():

    # TODO: create a function to ensure container is running
    sleep(1)  # sleep to make sure that predifined models uploaded
    set_openai_api_key_to_environment()

    # Create configurations
    llm_id = get_llm_model()
    config_id = create_config(llm_id=llm_id)
    config_id_2 = create_config(llm_id=llm_id)

    wikipedia_crew_id = create_wikipedia_crew(config_id)
    author_crew_id = create_author_crew(config_id_2)
    user_crew_id = create_user_crew(config_id)

    graph_id = create_graph("Integration graph2")  # TODO: Change this

    create_crew_node(
        crew_id=wikipedia_crew_id,
        node_name="wiki_crew_node",
        graph_id=graph_id,
        input_map={},
        output_variable_path="variables",
    )
    create_crew_node(
        crew_id=author_crew_id,
        node_name="author_crew_node",
        graph_id=graph_id,
        input_map={
            "user_id": "variables.user_name",
        },
        output_variable_path="variables.result",
    )
    create_crew_node(
        crew_id=user_crew_id,
        node_name="user_crew_node",
        graph_id=graph_id,
        input_map={
            "user_id": "variables.user_id",
        },
        output_variable_path="variables",
    )
    create_llm_node(
        llm_config_id=config_id,
        node_name="llm_node1",
        graph_id=graph_id,
        input_map={
            "query": "variables.query",
        },
        output_variable_path="variables",
    )
    create_start_node(graph_id=graph_id)
    create_hash_message_python_node(graph_id=graph_id)
    create_option_1_python_node(graph_id=graph_id)
    create_option_2_python_node(graph_id=graph_id)
    create_edge(start_key="__start__", end_key="hash_message", graph=graph_id)
    create_edge(start_key="hash_message", end_key="user_crew_node", graph=graph_id)
    create_user_name_conditional_edge(source="user_crew_node", graph=graph_id)

    create_edge(start_key="option_1", end_key="llm_node1", graph=graph_id)

    create_edge(start_key="option_2", end_key="author_crew_node", graph=graph_id)
    create_edge(start_key="author_crew_node", end_key="wiki_crew_node", graph=graph_id)

    # Run sessions
    session1 = run_session(
        graph_id=graph_id,
        variables={"user_id": 14, "secret_message": "hello, crew"},
    )
    logger.success(f"Session with id {session1} created, yay!")
    # session2 = run_session(
    #     graph_id=graph_id,
    #     initial_state={"user_id": 2, "secret_message": "hello, crew 2"},
    #     entry_point="hash_message",
    # )
    # logger.success(f"Session with id {session2} created, yay!")

    wait_for_results(session_id=session1)
    # wait_for_results(session_id=session2)
    delete_session(session_id=session1)


@pytest.mark.asyncio
async def test_knowledges(collection_id, redis_service):
    """Knowledges created in 'collection_id' fixture"""
    test_query = "What makes MYM different from other logistics platforms?"

    # Execute the knowledge search
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


@pytest.mark.skip
def test_get_tool_class_data():

    tool_list_response = requests.get(f"{MANAGER_URL}/tool/list", headers={"Host": rhost})
    validate_response(response=tool_list_response)
    tool_alias_list = tool_list_response.json()["tool_list"]

    error_tools = []
    for tool_alias in tool_alias_list:
        tool_class_data_response = requests.get(
            f"{MANAGER_URL}/tool/{tool_alias}/class-data",
            headers={"Host": rhost}
        )
        try:
            validate_response(response=tool_class_data_response)
            tool_alias_list = tool_class_data_response.json()["classdata"]
            print(tool_alias)
        except HTTPError as e:
            error_tools.append(
                {"tool_alias": tool_alias, "message": tool_class_data_response.reason}
            )

    if error_tools:
        assert False, str(error_tools)


def create_wikipedia_crew(llm_config_id):
    # Create Wikipedia agent and crew
    wikipedia_tool_config_id = create_wikipedia_tool_config()
    wiki_agent_id = create_wiki_agent(
        tool_config_id_list=[wikipedia_tool_config_id], config_id=llm_config_id
    )
    wiki_crew_id = create_crew(name="WIKIPEDIA CREW", agents=[wiki_agent_id])
    wiki_task_id, wiki_task_name = create_wiki_task(
        crew_id=wiki_crew_id, agent_id=wiki_agent_id
    )
    return wiki_crew_id


def create_user_crew(llm_config_id):
    # Create Wikipedia agent and crew
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


def create_wikipedia_tool_config() -> int:
    wikipedia_tool_id = get_tool("wikipedia")

    tool_config_data = {
        "name": "integration test wiki tool config",
        "tool": wikipedia_tool_id,
        "configuration": {},
    }
    return create_tool_config(**tool_config_data)


def create_wiki_task(crew_id: int, agent_id: int) -> tuple:
    task_data = {
        "name": f"Test wiki task {random.randint(1,100000)}",
        "instructions": "Find inpormation about cars",
        "expected_output": "What is car",
        "order": 1,
        "crew": crew_id,
        "agent": agent_id,
    }

    return create_task(**task_data)


def create_poem_task(crew_id: int, agent_id: int) -> tuple:

    task_data = {
        "name": f"Test write poem task {random.randint(1,100000)}",
        "instructions": "Write short rhyming poem about nature",
        "expected_output": "Short rhyming poem",
        "order": 1,
        "crew": crew_id,
        "agent": agent_id,
    }
    return create_task(**task_data)


def create_user_task(crew_id: int, agent_id: int) -> tuple:

    task_data = {
        "name": f"user task",
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


def create_wiki_agent(
    tool_config_id_list: list,
    config_id: int,
) -> int:
    agent_data = {
        "configured_tools": tool_config_id_list,
        "role": "wikipedia_searcher",
        "goal": "search information in wikipedia",
        "backstory": "You are the agent who use tools to perform tasks",
        "allow_delegation": False,
        "memory": False,
        "max_iter": 15,
        "llm_config": config_id,
        "fcm_llm_config": config_id,
    }
    return create_agent(**agent_data)


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
        "python_code_tools": python_code_tool_id_list,
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
    print(state["variables"])
    return ids.get(user_id, "Not found")
"""

    test_state = {"input": {"user_surname": "Zelensky"}}
    args_schema = {
        "type": "object",
        "title": "ArgumentsSchema",
        "properties": {
            "user_id": {"type": "integer", "description": "id of user"},
        },
    }

    tool_data = {
        "name": "python tool1",
        "description": "Get user name from id",
        "code": code,
        "entrypoint": "main",
        "libraries": ["requests"],
        "global_kwargs": {"state": test_state},
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


def create_user_name_conditional_edge(source: str, graph: int):
    code = """
def main():
    user_name = state["variables"]["user_name"]

    if user_name == "Artur":
        return "option_1"
    else:
        return "option_2"
"""

    conditional_edge_data = {
        "source": source,
        "graph": graph,
        "code": code,
    }
    return create_conditional_edge(**conditional_edge_data)


def get_llm_model(name: str = "gpt-4o-mini"):
    llm_model_response = requests.get(f"{DJANGO_URL}/llm-models?name={name}", headers={"Host": rhost})
    llm_model = None
    if llm_model_response.ok:
        results = llm_model_response.json()["results"]
        if len(results) > 0:
            llm_model = results[0]
    return llm_model["id"]
