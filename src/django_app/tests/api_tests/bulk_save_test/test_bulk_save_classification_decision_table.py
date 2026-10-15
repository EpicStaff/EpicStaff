import uuid

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationConditionGroupSection,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    Graph,
)
from tests.fixtures import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


def _cdt_list_url() -> str:
    return reverse("classificationdecisiontablenode-list")


def _make_cdt_node_payload(graph_id, group_name, *, temp_id=None):
    node = {
        "graph": graph_id,
        "node_name": "cdt_test_node",
        "condition_groups": [
            {
                "group_name": group_name,
                "order": 0,
            }
        ],
    }

    if temp_id is not None:
        node["temp_id"] = temp_id

    return node


# ---------------------------------------------------------------------------
# Bulk save — null/blank group_name → 400
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bulk_save_cdt_null_group_name_rejected(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "classification_decision_table_node_list": [
            _make_cdt_node_payload(graph.id, group_name=None),
        ],
    }
    resp = auth_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert "classification_decision_table_node_list" in resp.data["errors"]
    body = str(resp.content)
    assert "group_name" in body


@pytest.mark.django_db
def test_bulk_save_cdt_empty_string_group_name_rejected(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "classification_decision_table_node_list": [
            _make_cdt_node_payload(graph.id, group_name=""),
        ],
    }
    resp = auth_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert "classification_decision_table_node_list" in resp.data["errors"]
    body = str(resp.content)
    assert "group_name" in body


@pytest.mark.django_db
def test_bulk_save_cdt_whitespace_group_name_rejected(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "classification_decision_table_node_list": [
            _make_cdt_node_payload(graph.id, group_name="   "),
        ],
    }
    resp = auth_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert "classification_decision_table_node_list" in resp.data["errors"]
    body = str(resp.content)
    assert "group_name" in body


# ---------------------------------------------------------------------------
# Per-node POST — null/blank group_name → 400
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_per_node_post_null_group_name_rejected(auth_client, graph):
    payload = {
        "graph": graph.id,
        "node_name": "cdt_per_node",
        "condition_groups": [{"group_name": None, "order": 0}],
    }
    resp = auth_client.post(_cdt_list_url(), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    body = str(resp.content)
    assert "group_name" in body


@pytest.mark.django_db
def test_per_node_post_empty_string_group_name_rejected(auth_client, graph):
    payload = {
        "graph": graph.id,
        "node_name": "cdt_per_node_empty",
        "condition_groups": [{"group_name": "", "order": 0}],
    }
    resp = auth_client.post(_cdt_list_url(), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    body = str(resp.content)
    assert "group_name" in body


@pytest.mark.django_db
def test_per_node_post_whitespace_group_name_rejected(auth_client, graph):
    payload = {
        "graph": graph.id,
        "node_name": "cdt_per_node_ws",
        "condition_groups": [{"group_name": "   ", "order": 0}],
    }
    resp = auth_client.post(_cdt_list_url(), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    body = str(resp.content)
    assert "group_name" in body


# ---------------------------------------------------------------------------
# Regression — valid group_name succeeds
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bulk_save_cdt_valid_group_name_succeeds(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "classification_decision_table_node_list": [
            _make_cdt_node_payload(graph.id, group_name="valid_group"),
        ],
    }
    resp = auth_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content
    node = ClassificationDecisionTableNode.objects.get(
        graph=graph, node_name="cdt_test_node"
    )
    groups = ClassificationConditionGroup.objects.filter(
        classification_decision_table_node=node
    )
    assert groups.count() == 1
    assert groups.first().group_name == "valid_group"


@pytest.mark.django_db
def test_per_node_post_valid_group_name_succeeds(auth_client, graph):
    payload = {
        "graph": graph.id,
        "node_name": "cdt_per_node_valid",
        "condition_groups": [{"group_name": "good_name", "order": 0}],
    }
    resp = auth_client.post(_cdt_list_url(), payload, format="json")

    assert resp.status_code == status.HTTP_201_CREATED, resp.content
    node = ClassificationDecisionTableNode.objects.get(
        graph=graph, node_name="cdt_per_node_valid"
    )
    groups = ClassificationConditionGroup.objects.filter(
        classification_decision_table_node=node
    )
    assert groups.count() == 1
    assert groups.first().group_name == "good_name"


# ---------------------------------------------------------------------------
# Condition group metadata survives an update, on both write paths
# ---------------------------------------------------------------------------


def _cdt_detail_url(node_id: int) -> str:
    return reverse("classificationdecisiontablenode-detail", args=[node_id])


def _bulk_save(client, graph, node: dict):
    graph.refresh_from_db()
    payload = {
        "save_version": graph.save_version,
        "classification_decision_table_node_list": [node],
    }
    return client.post(_save_url(graph.id), payload, format="json")


@pytest.mark.django_db
def test_per_node_update_writes_condition_group_metadata(auth_client, graph):
    create_resp = auth_client.post(
        _cdt_list_url(),
        {
            "graph": graph.id,
            "node_name": "cdt_metadata",
            "condition_groups": [{"group_name": "g1", "order": 0, "metadata": {"color": "red"}}],
        },
        format="json",
    )
    assert create_resp.status_code == status.HTTP_201_CREATED, create_resp.content
    node_id = create_resp.data["id"]

    update_resp = auth_client.patch(
        _cdt_detail_url(node_id),
        {"condition_groups": [{"group_name": "g1", "order": 0, "metadata": {"color": "blue"}}]},
        format="json",
    )

    assert update_resp.status_code == status.HTTP_200_OK, update_resp.content
    group = ClassificationConditionGroup.objects.get(classification_decision_table_node_id=node_id)
    assert group.metadata == {"color": "blue"}


@pytest.mark.django_db
def test_bulk_save_update_writes_condition_group_metadata(auth_client, graph):
    node = {"graph": graph.id, "node_name": "cdt_metadata_bulk"}
    create_resp = _bulk_save(
        auth_client,
        graph,
        {
            **node,
            "condition_groups": [{"group_name": "g1", "order": 0, "metadata": {"color": "red"}}],
        },
    )
    assert create_resp.status_code == status.HTTP_200_OK, create_resp.content
    cdt = ClassificationDecisionTableNode.objects.get(graph=graph)
    group_id = ClassificationConditionGroup.objects.get(classification_decision_table_node=cdt).id

    update_resp = _bulk_save(
        auth_client,
        graph,
        {
            **node,
            "id": cdt.id,
            "condition_groups": [{"group_name": "g1", "order": 0, "metadata": {"color": "blue"}}],
        },
    )

    assert update_resp.status_code == status.HTTP_200_OK, update_resp.content
    group = ClassificationConditionGroup.objects.get(classification_decision_table_node=cdt)
    assert group.id == group_id
    assert group.metadata == {"color": "blue"}


# ---------------------------------------------------------------------------
# Condition group prompt resolution — bulk save matches the single-node path
# ---------------------------------------------------------------------------


@pytest.fixture
def cdt_with_prompted_group(graph):
    node = ClassificationDecisionTableNode.objects.create(graph=graph, node_name="cdt_prompt")
    prompt = ClassificationDecisionTablePrompt.objects.create(cdt_node=node, prompt_key="p1")
    ClassificationConditionGroup.objects.create(
        classification_decision_table_node=node,
        group_name="g1",
        order=0,
        prompt=prompt,
    )
    return node, prompt


@pytest.mark.django_db
def test_bulk_save_clearing_group_prompt_writes_null(auth_client, graph, cdt_with_prompted_group):
    node, _ = cdt_with_prompted_group

    # The flow editor sends both references as null when a group's prompt is cleared.
    resp = _bulk_save(
        auth_client,
        graph,
        {
            "id": node.id,
            "graph": graph.id,
            "node_name": node.node_name,
            "condition_groups": [
                {"group_name": "g1", "order": 0, "prompt_key": None, "prompt": None}
            ],
        },
    )

    assert resp.status_code == status.HTTP_200_OK, resp.content
    group = ClassificationConditionGroup.objects.get(classification_decision_table_node=node)
    assert group.prompt_id is None


@pytest.mark.django_db
def test_bulk_save_unknown_group_prompt_key_unlinks_prompt(
    auth_client, graph, cdt_with_prompted_group
):
    node, _ = cdt_with_prompted_group

    # The flow editor keeps a group's key after its prompt is deleted or renamed and
    # sends it with a null numeric id.
    resp = _bulk_save(
        auth_client,
        graph,
        {
            "id": node.id,
            "graph": graph.id,
            "node_name": node.node_name,
            "condition_groups": [
                {"group_name": "g1", "order": 0, "prompt_key": "deleted-prompt", "prompt": None}
            ],
        },
    )

    assert resp.status_code == status.HTTP_200_OK, resp.content
    group = ClassificationConditionGroup.objects.get(classification_decision_table_node=node)
    assert group.prompt_id is None


def _assert_item_rejected_and_rolled_back(resp, graph, version_before, node, *, index, error):
    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    errors = resp.data["errors"]["classification_decision_table_node_list"]
    assert errors == [{"index": index, "errors": [error]}]
    # The whole save rolls back: the node, its group and the version are untouched.
    node.refresh_from_db()
    assert node.node_name == "cdt_prompt"
    assert not ClassificationDecisionTableNode.objects.filter(node_name="cdt_new").exists()
    graph.refresh_from_db()
    assert graph.save_version == version_before


@pytest.mark.django_db
def test_bulk_save_unknown_group_prompt_id_rejected(auth_client, graph, cdt_with_prompted_group):
    node, prompt = cdt_with_prompted_group
    other_node = ClassificationDecisionTableNode.objects.create(graph=graph, node_name="cdt_other")
    foreign_prompt = ClassificationDecisionTablePrompt.objects.create(
        cdt_node=other_node, prompt_key="p_other"
    )
    graph.refresh_from_db()
    version_before = graph.save_version

    resp = auth_client.post(
        _save_url(graph.id),
        {
            "save_version": version_before,
            "classification_decision_table_node_list": [
                {"graph": graph.id, "node_name": "cdt_new"},
                {
                    "id": node.id,
                    "graph": graph.id,
                    "node_name": "renamed",
                    "condition_groups": [
                        {"group_name": "g1", "order": 0, "prompt": foreign_prompt.id}
                    ],
                },
            ],
        },
        format="json",
    )

    _assert_item_rejected_and_rolled_back(
        resp,
        graph,
        version_before,
        node,
        index=1,
        error=f"Prompt {foreign_prompt.id} doesn't exist or belong to another organization.",
    )
    group = ClassificationConditionGroup.objects.get(classification_decision_table_node=node)
    assert group.prompt_id == prompt.id
    assert not ClassificationConditionGroup.objects.filter(prompt=foreign_prompt).exists()


@pytest.mark.django_db
def test_bulk_save_unknown_group_section_rejected_per_item(
    auth_client, graph, cdt_with_prompted_group
):
    node, _ = cdt_with_prompted_group
    graph.refresh_from_db()
    version_before = graph.save_version
    missing_section_id = "00000000-0000-0000-0000-000000000001"

    resp = auth_client.post(
        _save_url(graph.id),
        {
            "save_version": version_before,
            "classification_decision_table_node_list": [
                {"graph": graph.id, "node_name": "cdt_new"},
                {
                    "id": node.id,
                    "graph": graph.id,
                    "node_name": "renamed",
                    "condition_groups": [
                        {"group_name": "g1", "order": 0, "section": missing_section_id}
                    ],
                },
            ],
        },
        format="json",
    )

    _assert_item_rejected_and_rolled_back(
        resp,
        graph,
        version_before,
        node,
        index=1,
        error=f"Section {missing_section_id} doesn't exist on this node.",
    )
    group = ClassificationConditionGroup.objects.get(classification_decision_table_node=node)
    assert group.section_id is None


@pytest.mark.django_db
def test_per_node_group_prompt_key_wins_over_stale_prompt_id(
    auth_client, graph, cdt_with_prompted_group
):
    node, prompt = cdt_with_prompted_group
    stale_prompt_id = prompt.id + 1_000_000

    resp = auth_client.patch(
        _cdt_detail_url(node.id),
        {
            "condition_groups": [
                {"group_name": "g1", "order": 0, "prompt_key": "p1", "prompt": stale_prompt_id}
            ]
        },
        format="json",
    )

    assert resp.status_code == status.HTTP_200_OK, resp.content
    group = ClassificationConditionGroup.objects.get(classification_decision_table_node=node)
    assert group.prompt_id == prompt.id


def _post_rename_with(client, graph, version_before, node, **node_fields):
    """Bulk save a new node plus an update of `node`; the update carries `node_fields`."""
    return client.post(
        _save_url(graph.id),
        {
            "save_version": version_before,
            "classification_decision_table_node_list": [
                {"graph": graph.id, "node_name": "cdt_new"},
                {"id": node.id, "graph": graph.id, "node_name": "renamed", **node_fields},
            ],
        },
        format="json",
    )


@pytest.mark.django_db
def test_bulk_save_group_value_of_wrong_type_rejected_per_item(
    auth_client, graph, cdt_with_prompted_group
):
    node, prompt = cdt_with_prompted_group
    graph.refresh_from_db()
    version_before = graph.save_version

    resp = _post_rename_with(
        auth_client,
        graph,
        version_before,
        node,
        condition_groups=[{"group_name": "g1", "order": "first", "dock_visible": "sometimes"}],
    )

    _assert_item_rejected_and_rolled_back(
        resp,
        graph,
        version_before,
        node,
        index=1,
        error={
            "condition_groups": [
                {
                    "order": ["A valid integer is required."],
                    "dock_visible": ["Must be a valid boolean."],
                }
            ]
        },
    )
    group = ClassificationConditionGroup.objects.get(classification_decision_table_node=node)
    assert (group.order, group.dock_visible, group.prompt_id) == (0, True, prompt.id)


@pytest.mark.django_db
def test_bulk_save_writes_the_validated_group_values(auth_client, graph, cdt_with_prompted_group):
    node, prompt = cdt_with_prompted_group
    group_id = ClassificationConditionGroup.objects.get(classification_decision_table_node=node).id

    # Accepted by the group serializer, but not by the model fields as sent: they must be
    # written in their validated form, the same as the single-node path writes them.
    resp = _bulk_save(
        auth_client,
        graph,
        {
            "id": node.id,
            "graph": graph.id,
            "node_name": node.node_name,
            "condition_groups": [
                {
                    "group_name": "  g1  ",
                    "order": "3.0",
                    "dock_visible": "yes",
                    "continue_flag": "on",
                    "prompt_key": "p1",
                }
            ],
        },
    )

    assert resp.status_code == status.HTTP_200_OK, resp.content
    group = ClassificationConditionGroup.objects.get(classification_decision_table_node=node)
    assert (group.id, group.group_name, group.order) == (group_id, "g1", 3)
    assert (group.dock_visible, group.continue_flag, group.prompt_id) == (True, True, prompt.id)


# ---------------------------------------------------------------------------
# A section id owned by another node is a conflict even when that section is
# soft-deleted: its id still occupies the primary key.
# ---------------------------------------------------------------------------


@pytest.fixture
def soft_deleted_foreign_section(other_org) -> ClassificationConditionGroupSection:
    foreign_graph = Graph.objects.create(name="foreign_graph", org=other_org)
    foreign_node = ClassificationDecisionTableNode.objects.create(
        graph=foreign_graph, node_name="foreign_cdt"
    )
    section = ClassificationConditionGroupSection.objects.create(
        id=uuid.uuid4(), classification_decision_table_node=foreign_node, name="foreign"
    )
    ClassificationConditionGroupSection.all_objects.filter(pk=section.pk).update(
        active=False, soft_deleted_at=timezone.now()
    )
    return section


def _assert_foreign_section_untouched(section) -> None:
    stored = ClassificationConditionGroupSection.all_objects.get(pk=section.pk)
    assert (stored.classification_decision_table_node_id, stored.name, stored.active) == (
        section.classification_decision_table_node_id,
        "foreign",
        False,
    )


@pytest.mark.django_db
def test_bulk_save_soft_deleted_section_of_another_node_rejected_per_item(
    auth_client, graph, cdt_with_prompted_group, soft_deleted_foreign_section
):
    node, _ = cdt_with_prompted_group
    graph.refresh_from_db()
    version_before = graph.save_version
    section_id = str(soft_deleted_foreign_section.id)

    resp = _post_rename_with(
        auth_client,
        graph,
        version_before,
        node,
        sections=[{"id": section_id, "name": "taken"}],
    )

    _assert_item_rejected_and_rolled_back(
        resp,
        graph,
        version_before,
        node,
        index=1,
        error=f"Section {section_id} already belongs to another node.",
    )
    _assert_foreign_section_untouched(soft_deleted_foreign_section)


@pytest.mark.django_db
def test_per_node_post_soft_deleted_section_of_another_node_rejected(
    auth_client, graph, soft_deleted_foreign_section
):
    section_id = str(soft_deleted_foreign_section.id)

    resp = auth_client.post(
        _cdt_list_url(),
        {
            "graph": graph.id,
            "node_name": "cdt_section_conflict",
            "sections": [{"id": section_id, "name": "taken"}],
        },
        format="json",
    )

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert resp.json() == {
        "status_code": 400,
        "code": "section_id_conflict",
        "message": f"Section {section_id} already belongs to another node.",
    }
    assert not ClassificationDecisionTableNode.objects.filter(
        node_name="cdt_section_conflict"
    ).exists()
    _assert_foreign_section_untouched(soft_deleted_foreign_section)
