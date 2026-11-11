import os
import sys

import pytest

# litellm otherwise fetches its price map from GitHub on import; tests price from the bundled copy.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

# agent root → resolves `app.*`
_agent_root = os.path.dirname(os.path.abspath(__file__))
# src root → resolves `shared.*` (mirrors PYTHONPATH=/app/src in Docker)
_src_root = os.path.dirname(_agent_root)

for _path in (_src_root, _agent_root):
    if _path not in sys.path:
        sys.path.insert(0, _path)


@pytest.fixture(scope="session", autouse=True)
def _mcp_sdk_logs_go_through_redaction():
    """Route the mcp SDK's log records as main() does, so tests see what the agent logs."""
    from app.logging_utils import route_mcp_sdk_logs_to_loguru

    route_mcp_sdk_logs_to_loguru()
