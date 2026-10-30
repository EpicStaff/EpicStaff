"""
org_id must be forced into global_kwargs so sandboxed callback tools
(fanout_tool, subflow_tool, schedule_manager_tool) can read
`globals()["org_id"]` and send X-Organization-Id to org-scoped Django
endpoints. org_id is resolved server-side (Graph.org_id, via
converter_service) and must always win over a same-named agent/tool-config
value in additional_global_kwargs -- mirrors the "session_id always wins"
treatment in crew_node.py.
"""

import pytest


@pytest.mark.asyncio
async def test_run_code_forces_org_id_into_global_kwargs_and_wins_over_additional(
    run_code, sandbox, make_python_code_data
):
    await run_code(
        python_code_data=make_python_code_data(global_kwargs={"foo": "bar"}, org_id=77),
        inputs={},
        additional_global_kwargs={"org_id": "agent-spoofed-value"},
    )

    assert sandbox.submitted["global_kwargs"] == {"foo": "bar", "org_id": 77}


@pytest.mark.asyncio
async def test_run_code_omits_org_id_when_not_set(run_code, sandbox, make_python_code_data):
    await run_code(
        python_code_data=make_python_code_data(global_kwargs={"foo": "bar"}),
        inputs={},
        additional_global_kwargs={},
    )

    assert "org_id" not in sandbox.submitted["global_kwargs"]


@pytest.mark.asyncio
async def test_run_code_forces_session_id_into_global_kwargs_and_wins_over_author_values(
    run_code, sandbox, make_python_code_data
):
    await run_code(
        python_code_data=make_python_code_data(
            global_kwargs={"foo": "bar", "session_id": 111}, session_id=5
        ),
        inputs={},
        additional_global_kwargs={"session_id": "agent-spoofed-value"},
    )

    assert sandbox.submitted["global_kwargs"] == {"foo": "bar", "session_id": 5}


@pytest.mark.asyncio
async def test_run_code_leaves_session_id_alone_when_not_set(
    run_code, sandbox, make_python_code_data
):
    await run_code(
        python_code_data=make_python_code_data(global_kwargs={"foo": "bar"}),
        inputs={},
    )

    assert "session_id" not in sandbox.submitted["global_kwargs"]
