"""
Coverage for RealtimeSurfaceService's storage-grant resolution.

A realtime agent-definition's python tools previously always got
storage_allowed_paths=None / storage_org_prefix=None, regardless of what the
agent-definition's surface actually granted, because the surface's
storage_items were never read at all. These tests pin down:
- the allow-flag inclusion rule for `_resolve_storage_grants`
- the end-to-end wiring into the resolved tool's PythonCodeToolData
"""

from __future__ import annotations

import pytest

from agents.models import AgentDefinition, Surface
from agents.models.agent_models import AgentDefaultSurface, SurfacePlace
from agents.models.surface_models import SurfacePythonTool, SurfaceStorageItem, ToolMode
from tables.models.graph_models import StorageFile
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.rbac_models import Organization
from tables.services.converter_service import ConverterService
from tables.services.realtime_surface_service import RealtimeSurfaceService


@pytest.fixture
def org(db):
    return Organization.objects.create(name="realtime-surface-storage-org")


@pytest.fixture
def agent_definition(db, org):
    return AgentDefinition.objects.create(
        organization=org,
        name="realtime-surface-storage-agent",
        instructions="do things",
    )


@pytest.fixture
def surface(db, org):
    return Surface.objects.create(
        organization=org,
        name="realtime-surface-storage-surface",
        instructions="",
    )


@pytest.fixture
def storage_py_tool(db):
    code = PythonCode.objects.create(code="def main(**kw): return kw")
    return PythonCodeTool.objects.create(
        name="realtime-surface-storage-py-tool",
        description="test",
        python_code=code,
        use_storage=True,
    )


@pytest.fixture
def resolver():
    return RealtimeSurfaceService(converter_service=ConverterService())


def _attach_default_surface(agent_definition, surface):
    AgentDefaultSurface.objects.create(
        agent_definition=agent_definition, surface=surface, place=SurfacePlace.REALTIME
    )


@pytest.mark.django_db
class TestResolveStorageGrants:
    def test_no_grants_returns_empty(self, resolver):
        allowed_paths, org_prefix = resolver._resolve_storage_grants([])

        assert allowed_paths == []
        assert org_prefix is None

    def test_file_with_only_unset_flags_is_excluded(self, resolver, org):
        storage_file = StorageFile.objects.create(
            org=org, name="a.txt", path="a.txt"
        )

        allowed_paths, org_prefix = resolver._resolve_storage_grants(
            [{"storage_file": storage_file.pk}]
        )

        assert allowed_paths == []
        assert org_prefix is None

    def test_file_with_any_allow_flag_is_included(self, resolver, org):
        storage_file = StorageFile.objects.create(
            org=org, name="b.txt", path="notes/b.txt"
        )

        allowed_paths, org_prefix = resolver._resolve_storage_grants(
            [
                {
                    "storage_file": storage_file.pk,
                    "can_list": "deny",
                    "can_view": "allow",
                    "can_edit": "unset",
                    "can_delete": "unset",
                }
            ]
        )

        assert allowed_paths == ["notes/b.txt"]
        assert org_prefix == f"org_{org.pk}"

    def test_deny_only_file_is_excluded(self, resolver, org):
        storage_file = StorageFile.objects.create(
            org=org, name="c.txt", path="c.txt"
        )

        allowed_paths, org_prefix = resolver._resolve_storage_grants(
            [{"storage_file": storage_file.pk, "can_view": "deny"}]
        )

        assert allowed_paths == []
        assert org_prefix is None


@pytest.mark.django_db
class TestResolveEndToEnd:
    def test_realtime_agent_definition_tool_gets_storage_wired(
        self, agent_definition, surface, storage_py_tool, org
    ):
        """The confirmed bug: a realtime agent-definition's python tool must
        receive the surface's granted storage paths/org-prefix even though no
        graph_id exists for this session."""
        storage_file = StorageFile.objects.create(
            org=org, name="report.txt", path="reports/report.txt"
        )
        SurfacePythonTool.objects.create(
            surface=surface, python_tool=storage_py_tool, mode=ToolMode.ALLOW
        )
        SurfaceStorageItem.objects.create(
            surface=surface, storage_file=storage_file, can_view="allow"
        )
        _attach_default_surface(agent_definition, surface)

        resolution = RealtimeSurfaceService(
            converter_service=ConverterService()
        ).resolve(agent_definition)

        assert len(resolution.tools) == 1
        python_code = resolution.tools[0].data.python_code
        assert python_code.storage_allowed_paths == ["reports/report.txt"]
        assert python_code.storage_org_prefix == f"org_{org.pk}"
        assert python_code.org_id == org.pk

    def test_realtime_agent_definition_tool_without_storage_grant_gets_none(
        self, agent_definition, surface, storage_py_tool
    ):
        """No storage grant on the surface -> the tool gets an explicit empty
        allow-list (deny-by-default), not an unresolved/unrestricted None."""
        SurfacePythonTool.objects.create(
            surface=surface, python_tool=storage_py_tool, mode=ToolMode.ALLOW
        )
        _attach_default_surface(agent_definition, surface)

        resolution = RealtimeSurfaceService(
            converter_service=ConverterService()
        ).resolve(agent_definition)

        assert len(resolution.tools) == 1
        python_code = resolution.tools[0].data.python_code
        assert python_code.storage_allowed_paths == []
        assert python_code.storage_org_prefix is None
        # org_id is unconditional (not gated on use_storage/grants) -- always
        # the agent-definition's own authoritative org.
        assert python_code.org_id == agent_definition.organization_id
