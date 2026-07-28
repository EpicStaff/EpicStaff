import json
from requests import HTTPError, Response
import requests
import time
from loguru import logger

from utils.variables import DJANGO_URL, TEST_TOOL_NAME
from utils.utils import get_headers


def validate_response(response: Response) -> None:
    try:
        response.raise_for_status()
    except HTTPError:
        logger.error(response.content)
        raise


def delete_session(session_id: int):
    get_url = f"{DJANGO_URL}/sessions/{session_id}"
    delete_url = f"{DJANGO_URL}/sessions/{session_id}/"

    response = requests.get(get_url, headers=get_headers())
    validate_response(response)
    assert response.status_code == 200
    assert response.json()["id"] == session_id

    response = requests.delete(delete_url, headers=get_headers())
    assert response.status_code == 204
    assert not response.content

    response = requests.get(get_url, headers=get_headers())
    assert response.status_code == 404

    logger.info(f"Session {session_id} deleted")


def delete_crews(crew_ids_to_delete: list):
    """Delete crews, related agents and tasks"""
    for crew_id in crew_ids_to_delete:
        crew_url = f"{DJANGO_URL}/crews/{crew_id}/"
        crew_data_response = requests.get(crew_url, headers=get_headers())
        crew_data = json.loads(crew_data_response.content)

        agents = crew_data.get("agents")
        tasks = crew_data.get("tasks")

        for agent_id in agents:
            agent_url = f"{DJANGO_URL}/agents/{agent_id}/"

            agent_response = requests.delete(agent_url, headers=get_headers())
            assert agent_response.status_code == 204
            assert not agent_response.content

        for task_id in tasks:
            task_url = f"{DJANGO_URL}/tasks/{task_id}/"
            task_response = requests.delete(task_url, headers=get_headers())
            assert task_response.status_code == 204
            assert not task_response.content

        response = requests.delete(crew_url, headers=get_headers())
        assert response.status_code == 204
        assert not response.content
        time.sleep(0.1)


def delete_graph(graph_id: int):
    delete_url = f"{DJANGO_URL}/graphs/{graph_id}/"
    response = requests.delete(delete_url, headers=get_headers())
    assert response.status_code == 204
    assert not response.content


def delete_custom_tools():
    custom_tools_response = requests.get(
        f"{DJANGO_URL}/python-code-tool/", headers=get_headers()
    )
    custom_tools_data = json.loads(custom_tools_response.content)
    tools = custom_tools_data.get("results", [])
    for tool in tools:
        if TEST_TOOL_NAME in tool.get("name"):
            tool_id = tool.get("id")
            tool_url = f"{DJANGO_URL}/python-code-tool/{tool_id}/"
            response = requests.delete(tool_url, headers=get_headers())
            assert response.status_code == 204
            assert not response.content
