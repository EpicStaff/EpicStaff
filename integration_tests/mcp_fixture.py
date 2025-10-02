import time

import pytest
from utils.docker_utils import docker_compose_down, docker_compose_up

@pytest.fixture
def run_mcp_tool():
    """Pytest fixture to run MCP tool and ensure it's healthy."""
    try:
        docker_compose_up(project_dir="mcp-test-tool")
        time.sleep(5)
        yield 
    except Exception as e:
        assert False, f"{type(e).__name__}: {e}"
    finally:
        docker_compose_down(project_dir="mcp-test-tool")