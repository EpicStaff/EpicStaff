from __future__ import annotations

import pytest

from agents.exceptions import SurfaceValidationError
from agents.models.agent_models import AgentDefinition
from agents.models.surface_models import (
    AgentInlineSurfaceStorageItem,
    InlineSurface,
    InlineSurfaceStorageItem,
    Surface,
    SurfaceStorageItem,
)
from agents.services.agent_inline_surface_service import AgentInlineSurfaceService
from agents.services.inline_surface_service import InlineSurfaceService
from agents.services.surface_service import SurfaceService
from tables.models.graph_models import AgentNode, Graph, StorageFile, TaskNode
from rbac.models import Organization


@pytest.fixture
def org(db):
    return Organization.objects.create(name="surface-storage-org")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="surface-storage-other-org")


@pytest.fixture
def foreign_storage_file(other_org):
    return StorageFile.objects.create(
        org=other_org, name="foreign.txt", path="foreign.txt"
    )


@pytest.fixture
def graph(org):
    return Graph.objects.create(org=org, name="surface-storage-graph")


@pytest.fixture
def task_node(graph):
    return TaskNode.objects.create(graph=graph, node_name="surface-storage-task-node")


@pytest.fixture
def agent_node(graph):
    return AgentNode.objects.create(graph=graph, node_name="surface-storage-agent-node")


@pytest.mark.django_db
class TestSurfaceServiceCrossOrgStorage:
    def test_create_surface_with_foreign_org_storage_file_raises_and_writes_nothing(
        self, org, foreign_storage_file
    ):
        before_items = SurfaceStorageItem.objects.count()
        before_surfaces = Surface.objects.count()

        with pytest.raises(SurfaceValidationError):
            SurfaceService.create_surface(
                organization_id=org.pk,
                validated_data={
                    "name": "cross-org-create",
                    "storage_items": [
                        {
                            "storage_file": foreign_storage_file,
                            "can_list": "unset",
                            "can_view": "allow",
                            "can_edit": "unset",
                            "can_delete": "unset",
                        }
                    ],
                },
            )

        assert SurfaceStorageItem.objects.count() == before_items
        # transaction.atomic rolls back the whole create, including the Surface row
        assert Surface.objects.count() == before_surfaces

    def test_update_surface_with_foreign_org_storage_file_raises_and_writes_nothing(
        self, org, foreign_storage_file
    ):
        surface = Surface.objects.create(organization=org, name="cross-org-update")
        before_items = SurfaceStorageItem.objects.count()

        with pytest.raises(SurfaceValidationError):
            SurfaceService.update_surface(
                instance=surface,
                validated_data={
                    "storage_items": [
                        {
                            "storage_file": foreign_storage_file,
                            "can_list": "unset",
                            "can_view": "allow",
                            "can_edit": "unset",
                            "can_delete": "unset",
                        }
                    ],
                },
                partial=True,
            )

        assert SurfaceStorageItem.objects.count() == before_items
        assert Surface.objects.filter(pk=surface.pk).exists()


@pytest.mark.django_db
class TestInlineSurfaceServiceCrossOrgStorage:
    def test_apply_with_foreign_org_storage_file_raises_and_writes_nothing(
        self, task_node, foreign_storage_file
    ):
        before_items = InlineSurfaceStorageItem.objects.count()

        with pytest.raises(SurfaceValidationError):
            InlineSurfaceService.apply(
                task_node=task_node,
                data={
                    "instructions": "",
                    "storage_items": [
                        {
                            "storage_file": foreign_storage_file,
                            "can_list": "unset",
                            "can_view": "allow",
                            "can_edit": "unset",
                            "can_delete": "unset",
                        }
                    ],
                },
            )

        assert InlineSurfaceStorageItem.objects.count() == before_items
        # transaction.atomic rolls back the update_or_create'd InlineSurface too
        assert not InlineSurface.objects.filter(task_node=task_node).exists()


@pytest.mark.django_db
class TestAgentInlineSurfaceServiceCrossOrgStorage:
    def test_apply_with_foreign_org_storage_file_raises_and_writes_nothing(
        self, agent_node, foreign_storage_file
    ):
        before_items = AgentInlineSurfaceStorageItem.objects.count()

        with pytest.raises(SurfaceValidationError):
            AgentInlineSurfaceService.apply(
                agent_node=agent_node,
                data={
                    "instructions": "",
                    "storage_items": [
                        {
                            "storage_file": foreign_storage_file,
                            "can_list": "unset",
                            "can_view": "allow",
                            "can_edit": "unset",
                            "can_delete": "unset",
                        }
                    ],
                },
            )

        assert AgentInlineSurfaceStorageItem.objects.count() == before_items
