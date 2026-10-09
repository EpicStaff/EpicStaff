"""Flow import must gate every created entity on CREATE for its RBAC resource.

A flow file can carry any importable entity type next to the flow itself, and
each one the import creates (rather than reuses) has to pass the same CREATE
check its own API endpoint applies. These cases cover the entity types whose
endpoints are permission-gated: provider realtime configs (LLM_CONFIGS),
agent definitions (AGENTS) and surfaces (SURFACES).

Source entities live in `beta`; the import lands in `acme`. find_existing is
org-scoped, so every carried entity is genuinely created in `acme`.
"""

import json
from dataclasses import dataclass
from typing import Callable

import pytest
from django.db.models import Model
from django.urls import reverse

from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

from agents.models import AgentDefinition, Surface
from rbac.models import OrganizationUser, Role
from rbac.models.enums import Permission, ResourceType
from rbac.models.role import RolePermission
from tables.import_export.enums import EntityType
from tables.models import Graph, StartNode
from tables.models.realtime_models import (
    ElevenLabsRealtimeConfig,
    GeminiRealtimeConfig,
    OpenAIRealtimeConfig,
)


@dataclass(frozen=True)
class CarriedEntityCase:
    entity_type: EntityType
    model: type[Model]
    resource: ResourceType
    create_source: Callable


def _create_openai_realtime_config(org):
    return OpenAIRealtimeConfig.objects.create(
        org=org, custom_name="openai realtime", model_name="gpt-realtime-1.5"
    )


def _create_elevenlabs_realtime_config(org):
    return ElevenLabsRealtimeConfig.objects.create(
        org=org, custom_name="elevenlabs realtime"
    )


def _create_gemini_realtime_config(org):
    return GeminiRealtimeConfig.objects.create(org=org, custom_name="gemini realtime")


def _create_agent_definition(org):
    return AgentDefinition.objects.create(
        org=org,
        name="carried agent definition",
        description="description",
        instruction_list=[{"name": "Instruction_1.md", "content": "instructions"}],
    )


def _create_surface(org):
    return Surface.objects.create(
        org=org, name="carried surface", instructions="instructions"
    )


CASES = [
    CarriedEntityCase(
        EntityType.OPENAI_REALTIME_CONFIG,
        OpenAIRealtimeConfig,
        ResourceType.LLM_CONFIGS,
        _create_openai_realtime_config,
    ),
    CarriedEntityCase(
        EntityType.ELEVENLABS_REALTIME_CONFIG,
        ElevenLabsRealtimeConfig,
        ResourceType.LLM_CONFIGS,
        _create_elevenlabs_realtime_config,
    ),
    CarriedEntityCase(
        EntityType.GEMINI_REALTIME_CONFIG,
        GeminiRealtimeConfig,
        ResourceType.LLM_CONFIGS,
        _create_gemini_realtime_config,
    ),
    CarriedEntityCase(
        EntityType.AGENT_DEFINITION,
        AgentDefinition,
        ResourceType.AGENTS,
        _create_agent_definition,
    ),
    CarriedEntityCase(
        EntityType.SURFACE,
        Surface,
        ResourceType.SURFACES,
        _create_surface,
    ),
]

REALTIME_CASES = [case for case in CASES if case.resource == ResourceType.LLM_CONFIGS]


def _case_id(case: CarriedEntityCase) -> str:
    return str(case.entity_type)


@pytest.fixture
def flows_only_importer(django_user_model, acme):
    """Acme user who may create flows but holds no other permission."""
    role = Role.objects.create(name="FlowsOnlyImporter", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.FLOWS,
        permissions=int(Permission.CREATE | Permission.READ),
    )
    user = django_user_model.objects.create_user(
        email="flows-only-importer@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role)
    return user


@pytest.fixture
def flow_file_carrying(beta, export_service, openai_realtime_builtin_model):
    """Factory: a flow export from `beta` that also carries one entity of the case's type."""

    def _build(case: CarriedEntityCase):
        graph = Graph.objects.create(
            name="carrier flow", metadata={"nodes": [], "edges": []}, org=beta
        )
        StartNode.objects.create(graph=graph, variables={})
        source_entity = case.create_source(beta)

        export_data = export_service.export_entities(EntityType.GRAPH, [graph.id])
        carried = export_service.export_entities(case.entity_type, [source_entity.id])
        export_data[case.entity_type] = carried[case.entity_type]
        return data_to_json_file(data=export_data, filename="flow.json")

    return _build


def _post_import(client_as, user, org, file):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client.post(
        reverse("graphs-import-entity"), {"file": file}, format="multipart"
    )


def _rows_in_org(case: CarriedEntityCase, org) -> int:
    return case.model.objects.filter(org=org).count()


@pytest.mark.django_db
class TestFlowImportGatesCarriedEntities:
    @pytest.mark.parametrize("case", CASES, ids=_case_id)
    def test_importer_without_create_on_resource_is_denied(
        self, case, acme, flows_only_importer, flow_file_carrying, client_as
    ):
        file = flow_file_carrying(case)

        response = _post_import(client_as, flows_only_importer, acme, file)

        assert response.status_code == 403
        assert case.resource.value in json.dumps(response.json())
        assert _rows_in_org(case, acme) == 0
        assert Graph.objects.filter(org=acme).count() == 0

    @pytest.mark.parametrize("case", REALTIME_CASES, ids=_case_id)
    def test_builtin_member_cannot_create_realtime_config_via_flow_import(
        self, case, acme, member_only, flow_file_carrying, client_as
    ):
        file = flow_file_carrying(case)

        response = _post_import(client_as, member_only, acme, file)

        assert response.status_code == 403
        assert ResourceType.LLM_CONFIGS.value in json.dumps(response.json())
        assert _rows_in_org(case, acme) == 0
        assert Graph.objects.filter(org=acme).count() == 0

    @pytest.mark.parametrize("case", CASES, ids=_case_id)
    def test_importer_with_create_on_resource_imports_entity(
        self, case, acme, admin_acme, flow_file_carrying, client_as
    ):
        file = flow_file_carrying(case)

        response = _post_import(client_as, admin_acme, acme, file)

        assert response.status_code == 200
        assert _rows_in_org(case, acme) == 1
        assert Graph.objects.filter(org=acme).count() == 1
