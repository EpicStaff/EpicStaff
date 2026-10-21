"""API responses render authors and last editors as user summaries, scoped to the caller's org."""

import json

import pytest
from django.urls import reverse
from drf_spectacular.generators import SchemaGenerator
from rest_framework import status

from rbac.authorship import record_last_edit
from rbac.governance.authorship import AuthorshipReleaseService
from rbac.models import OrganizationUser
from tables.models import Graph, LLMConfig
from tables.models.graph_models import GraphNote, SubGraphNode
from tables.models.llm_models import LLMModel
from tables.models.provider import Provider
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

AUTHOR_DISPLAY_NAME = "Acme Author Visible Only In Acme"


@pytest.fixture
def named_author(admin_acme):
    admin_acme.display_name = AUTHOR_DISPLAY_NAME
    admin_acme.save(update_fields=["display_name"])
    return admin_acme


@pytest.fixture
def beta_member(db, django_user_model, beta, role_member):
    user = django_user_model.objects.create_user(
        email="beta-member-summary@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=beta, role=role_member)
    return user


@pytest.fixture
def client_in(client_as):
    def _make(user, org):
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
        return client

    return _make


@pytest.fixture
def authored_note(acme, named_author):
    graph = Graph.objects.create(name="summary-flow", org=acme, created_by=named_author)
    note = GraphNote.objects.create(graph=graph, content="authored", created_by=named_author)
    record_last_edit(note, named_author)
    return note


@pytest.fixture
def authored_llm_config(acme, named_author):
    config = LLMConfig.objects.create(
        custom_name="summary-config", org=acme, created_by=named_author
    )
    record_last_edit(config, named_author)
    return config


EXPECTED_AUTHOR_KEYS = {"id", "display_name", "avatar_url"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url_name", "resource"),
    [("graphnote-detail", "authored_note"), ("llmconfig-detail", "authored_llm_config")],
)
def test_member_sees_author_and_editor_summaries(
    url_name, resource, request, client_in, named_author, acme
):
    row = request.getfixturevalue(resource)

    response = client_in(named_author, acme).get(reverse(url_name, args=[row.pk]))

    assert response.status_code == status.HTTP_200_OK, response.content
    expected = {"id": named_author.id, "display_name": AUTHOR_DISPLAY_NAME, "avatar_url": None}
    assert response.data["created_by"] == expected
    assert response.data["last_edited_by"] == expected
    assert set(response.data["created_by"]) == EXPECTED_AUTHOR_KEYS
    assert named_author.email not in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("url_name", "resource"),
    [("graphnote-detail", "authored_note"), ("llmconfig-detail", "authored_llm_config")],
)
def test_other_org_member_gets_404_without_the_author(
    url_name, resource, request, client_in, beta_member, beta
):
    row = request.getfixturevalue(resource)

    response = client_in(beta_member, beta).get(reverse(url_name, args=[row.pk]))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert AUTHOR_DISPLAY_NAME not in response.content.decode()


@pytest.mark.django_db
def test_other_org_lists_global_models_without_author_and_never_custom_ones(
    client_in, beta_member, beta, acme, named_author
):
    provider, _ = Provider.objects.get_or_create(name="openai")
    global_model = LLMModel.objects.create(name="summary-global", llm_provider=provider)
    LLMModel.objects.create(
        name="summary-acme-custom",
        llm_provider=provider,
        is_custom=True,
        org=acme,
        created_by=named_author,
    )

    response = client_in(beta_member, beta).get(reverse("llmmodel-list"), {"page_size": 1000})

    assert response.status_code == status.HTTP_200_OK, response.content
    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    listed = {row["name"]: row for row in rows}
    assert listed[global_model.name]["created_by"] is None
    assert "summary-acme-custom" not in listed
    assert AUTHOR_DISPLAY_NAME not in json.dumps(response.data)


@pytest.mark.django_db
def test_released_author_and_editor_render_as_null(
    client_in, authored_llm_config, named_author, acme, member_only
):
    AuthorshipReleaseService().release(user_id=named_author.id, org_id=acme.id)

    response = client_in(member_only, acme).get(
        reverse("llmconfig-detail", args=[authored_llm_config.pk])
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["created_by"] is None
    assert response.data["last_edited_by"] is None
    assert response.data["last_edited_at"] is not None


# ---- OpenAPI ----


@pytest.fixture(scope="module")
def openapi_components():
    return SchemaGenerator().get_schema(request=None, public=True)["components"]["schemas"]


def _is_nullable_user_summary(property_schema: dict) -> bool:
    variants = [
        property_schema,
        *property_schema.get("allOf", []),
        *property_schema.get("oneOf", []),
    ]
    references_summary = any(
        variant.get("$ref") == "#/components/schemas/UserSummary" for variant in variants
    )
    nullable = property_schema.get("nullable") is True or any(
        variant.get("type") == "null" for variant in variants
    )
    return references_summary and nullable


@pytest.mark.parametrize(
    ("component", "field_names"),
    [
        ("LLMConfig", ("created_by", "last_edited_by")),
        ("LLMModel", ("created_by",)),
        ("AgentNode", ("created_by", "last_edited_by")),
        ("StorageFile", ("last_edited_by",)),
        ("FileItem", ("last_edited_by",)),
    ],
)
def test_schema_documents_authorship_as_nullable_user_summary(
    openapi_components, component, field_names
):
    properties = openapi_components[component]["properties"]

    for field_name in field_names:
        assert _is_nullable_user_summary(properties[field_name]), properties[field_name]


def test_schema_user_summary_exposes_only_public_identity(openapi_components):
    assert set(openapi_components["UserSummary"]["properties"]) == EXPECTED_AUTHOR_KEYS


@pytest.fixture
def subgraph_node_edited_by_avatar_user(acme, named_author):
    named_author.avatar.name = f"avatars/{named_author.id}/summary-avatar.png"
    named_author.save(update_fields=["avatar"])
    parent = Graph.objects.create(name="summary-parent-flow", org=acme)
    referenced = Graph.objects.create(name="summary-referenced-flow", org=acme)
    record_last_edit(referenced, named_author)
    return SubGraphNode.objects.create(graph=parent, subgraph=referenced, node_name="sub")


@pytest.mark.django_db
def test_subgraph_detail_renders_editor_avatar_as_absolute_url(
    client_in, subgraph_node_edited_by_avatar_user, named_author, acme
):
    node = subgraph_node_edited_by_avatar_user
    client = client_in(named_author, acme)

    node_response = client.get(reverse("subgraphnode-detail", args=[node.pk]))
    graph_response = client.get(reverse("graphs-detail", args=[node.graph_id]))

    assert node_response.status_code == status.HTTP_200_OK, node_response.content
    assert graph_response.status_code == status.HTTP_200_OK, graph_response.content
    expected_avatar_url = f"http://testserver{named_author.avatar.url}"
    (graph_subgraph_node,) = graph_response.data["subgraph_node_list"]
    for subgraph_detail in (
        node_response.data["subgraph_detail"],
        graph_subgraph_node["subgraph_detail"],
    ):
        assert subgraph_detail["last_edited_by"]["avatar_url"] == expected_avatar_url
