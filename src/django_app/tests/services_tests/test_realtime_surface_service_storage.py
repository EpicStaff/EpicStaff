"""
Coverage for RealtimeSurfaceService's storage-grant resolution.

A realtime agent-definition's python tools previously always got
storage_allowed_paths=None / storage_org_prefix=None, regardless of what the
agent-definition's surface actually granted, because the surface's
storage_items were never read at all. These tests pin down, through resolve():
- which granted files count (the allow-flag inclusion rule)
- the wiring into the resolved tool's PythonCodeToolData
"""

from __future__ import annotations

import pytest

from agents.models import AgentDefinition, Surface
from agents.models.agent_models import AgentDefaultSurface, SurfacePlace
from agents.models.surface_models import SurfacePythonTool, SurfaceStorageItem, ToolMode
from tables.models.graph_models import StorageFile
from tables.models.python_models import PythonCode, PythonCodeTool
from rbac.models import Organization
from storage_credentials.exceptions import CredentialScopeValidationError
from tables.services.converter_service import ConverterService
from tables.services.realtime_surface_service import RealtimeSurfaceService


@pytest.fixture
def org(db):
    return Organization.objects.create(name="realtime-surface-storage-org")


@pytest.fixture
def agent_definition(db, org):
    return AgentDefinition.objects.create(
        org=org,
        name="realtime-surface-storage-agent",
        instruction_list=[{"name": "Instruction_1.md", "content": "do things"}],
    )


@pytest.fixture
def surface(db, org):
    return Surface.objects.create(org=org, name="realtime-surface-storage-surface", instructions="")


def _python_tool(name: str, use_storage: bool) -> PythonCodeTool:
    code = PythonCode.objects.create(code="def main(**kw): return kw")
    return PythonCodeTool.objects.create(name=name, description="test", python_code=code, use_storage=use_storage)


def _resolve(agent_definition, surface, tool):
    SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode=ToolMode.ALLOW)
    AgentDefaultSurface.objects.create(agent_definition=agent_definition, surface=surface, place=SurfacePlace.REALTIME)
    return RealtimeSurfaceService(converter_service=ConverterService()).resolve(agent_definition)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("grants", "expected_paths"),
    [
        ([{"path": "notes/b.txt", "can_list": "deny", "can_view": "allow"}], ["notes/b.txt"]),
        # Any ALLOW flag among list/view/edit/delete qualifies a file; unset or deny alone does not.
        ([{"path": "a.txt"}], None),
        ([{"path": "c.txt", "can_view": "deny"}], None),
        # Another org's file never reaches the tool, even when the surface names it.
        (
            [{"path": "own/own.txt", "can_view": "allow"}, {"path": "foreign/foreign.txt", "can_view": "allow", "foreign": True}],
            ["own/own.txt"],
        ),
    ],
    ids=["allow-flag", "only-unset-flags", "deny-only", "foreign-org-file"],
)
def test_storage_tool_gets_only_the_files_the_surface_allows(agent_definition, surface, org, grants, expected_paths):
    foreign_org = Organization.objects.create(name="realtime-surface-storage-foreign-org")
    for grant in grants:
        flags = {name: grant[name] for name in ("can_list", "can_view", "can_edit", "can_delete") if name in grant}
        storage_file = StorageFile.objects.create(
            org=foreign_org if grant.get("foreign") else org, name=grant["path"].rsplit("/", 1)[-1], path=grant["path"]
        )
        SurfaceStorageItem.objects.create(surface=surface, storage_file=storage_file, **flags)
    tool = _python_tool("realtime-surface-storage-py-tool", use_storage=True)

    if expected_paths is None:
        # Nothing usable granted: the agent must not start missing a capability its surface grants.
        with pytest.raises(CredentialScopeValidationError, match=tool.name):
            _resolve(agent_definition, surface, tool)
        return
    (resolved,) = _resolve(agent_definition, surface, tool).tools
    python_code = resolved.data.python_code
    assert python_code.storage_allowed_paths == expected_paths
    # The prefix and org always come from the agent's own org.
    assert (python_code.storage_org_prefix, python_code.org_id) == (f"org_{org.pk}", org.pk)


@pytest.mark.django_db
def test_tool_without_storage_gets_no_storage_scope_whatever_the_surface_grants(agent_definition, surface, org):
    storage_file = StorageFile.objects.create(org=org, name="report.txt", path="reports/report.txt")
    SurfaceStorageItem.objects.create(surface=surface, storage_file=storage_file, can_view="allow")

    (resolved,) = _resolve(agent_definition, surface, _python_tool("realtime-surface-plain-py-tool", use_storage=False)).tools

    python_code = resolved.data.python_code
    assert (python_code.storage_allowed_paths, python_code.storage_org_prefix) == (None, None)
    # org_id is not gated on storage: it is always the agent-definition's own org.
    assert python_code.org_id == agent_definition.org_id
