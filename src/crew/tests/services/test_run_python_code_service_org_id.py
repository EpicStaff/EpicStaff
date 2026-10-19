"""
org_id must be forced into global_kwargs (and carried on the typed
CodeTaskData field) so sandboxed callback tools (fanout_tool, subflow_tool,
schedule_manager_tool) can read `globals()["org_id"]` and send
X-Organization-Id to org-scoped Django endpoints. org_id is resolved
server-side (Graph.org_id, via converter_service) and must always win over a
same-named agent/tool-config value in additional_global_kwargs -- mirrors the
"session_id always wins" treatment in crew_node.py.
"""

import pytest

from src.shared.models import PythonCodeData


@pytest.fixture
def answering_sandbox(sandbox):
    sandbox.auto_reply = True
    return sandbox


def make_python_code_data(**overrides) -> PythonCodeData:
    defaults = dict(
        venv_name="default",
        code="def main(**kw): return kw",
        entrypoint="main",
        libraries=[],
        global_kwargs={},
    )
    defaults.update(overrides)
    return PythonCodeData(**defaults)


@pytest.mark.asyncio
async def test_run_code_forces_org_id_into_global_kwargs_and_wins_over_additional(
    run_python_code_service, answering_sandbox
):
    await run_python_code_service.run_code(
        python_code_data=make_python_code_data(global_kwargs={"foo": "bar"}, org_id=77),
        inputs={},
        additional_global_kwargs={"org_id": "agent-spoofed-value"},
    )

    [published] = answering_sandbox.tasks
    assert published["global_kwargs"]["org_id"] == 77
    assert published["global_kwargs"]["foo"] == "bar"
    assert published["org_id"] == 77


@pytest.mark.asyncio
async def test_run_code_omits_org_id_when_not_set(run_python_code_service, answering_sandbox):
    await run_python_code_service.run_code(
        python_code_data=make_python_code_data(global_kwargs={"foo": "bar"}),
        inputs={},
        additional_global_kwargs={},
    )

    [published] = answering_sandbox.tasks
    assert "org_id" not in published["global_kwargs"]
    assert published["org_id"] is None
