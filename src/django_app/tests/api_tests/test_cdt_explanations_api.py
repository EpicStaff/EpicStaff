"""PUT /api/classification-decision-table-node/{pk}/explanations/ — persists a CDT
node's step explanations and nothing else, versioned like the flow bulk save.

Bulk save is the other writer of `metadata.explanations`; the contract between the
two (one save_version, one definition of a valid entry) is tested at the bottom."""

import json
from unittest import mock

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import OrganizationUser
from tables.constants.cdt_explanation_limits import (
    MAX_EXPLANATION_TEXT_LENGTH,
    MAX_FINGERPRINT_LENGTH,
    MAX_GENERATED_BY_LENGTH,
    MAX_STEP_KEY_LENGTH,
    MAX_STORED_EXPLANATIONS,
    MAX_STORED_EXPLANATIONS_BYTES,
)
from tables.graph_collab.notifications import GraphEditNotifier
from tables.models import Graph
from tables.models.graph_models import ClassificationDecisionTableNode
from utils.logger import logger

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _url(node_id) -> str:
    return f"/api/classification-decision-table-node/{node_id}/explanations/"


def _bulk_save_url(graph_id) -> str:
    return f"/api/graphs/{graph_id}/save/"


def _send_json(client_method, url, body):
    # Sent pre-encoded: the test client's JSON renderer cannot encode a lone
    # surrogate, while `json.dumps` escapes it the way a browser would.
    return client_method(url, data=json.dumps(body), content_type="application/json")


def _bulk_save_payload(node, save_version, metadata) -> dict:
    return {
        "save_version": save_version,
        "classification_decision_table_node_list": [
            {"id": node.id, "graph": node.graph_id, "node_name": node.node_name, "metadata": metadata}
        ],
    }


def _full_texts(count) -> dict:
    return {
        f"step-{index}": _explanation(text="t" * MAX_EXPLANATION_TEXT_LENGTH)
        for index in range(count)
    }


def _explanation(text="Checks the score.", generated_by="gpt-4o-mini", fingerprint="fp-1"):
    return {"text": text, "generatedBy": generated_by, "fingerprint": fingerprint}


OTHER_METADATA = {"position": {"x": 10, "y": 20}, "color": "#fff", "nodeNumber": 3}


@pytest.fixture
def graph_acme(acme):
    return Graph.objects.create(name="flow-acme", metadata={}, org=acme)


@pytest.fixture
def cdt_node(graph_acme):
    return ClassificationDecisionTableNode.objects.create(
        graph=graph_acme,
        node_name="classify",
        metadata={**OTHER_METADATA, "explanations": {"old-step": _explanation(text="old")}},
    )


@pytest.fixture
def acme_client(client_as, acme):
    def _make(user):
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _make


@pytest.fixture
def viewer_acme(db, django_user_model, acme, role_viewer):
    user = django_user_model.objects.create_user(
        email="viewer-cdt-explanations@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role_viewer)
    return user


@pytest.fixture
def api_key_client(issue_api_key, acme):
    def _make(user):
        raw_key, _ = issue_api_key(user=user, name="cdt-explanations")
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _make


def _assert_untouched(node, graph):
    node.refresh_from_db()
    graph.refresh_from_db()
    assert node.metadata == {**OTHER_METADATA, "explanations": {"old-step": _explanation(text="old")}}
    assert graph.save_version == 1


# ---- success ----


@pytest.mark.django_db
def test_put_replaces_only_explanations(acme_client, admin_acme, cdt_node, graph_acme):
    hash_before = cdt_node.generate_hash()
    explanations = {"rule:a:condition": _explanation(), "pre": _explanation(text="Prepares.")}

    response = acme_client(admin_acme).put(
        _url(cdt_node.id), {"save_version": 1, "explanations": explanations}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json() == {"explanations": explanations, "save_version": 2}
    cdt_node.refresh_from_db()
    assert cdt_node.metadata == {**OTHER_METADATA, "explanations": explanations}
    assert cdt_node.node_name == "classify"
    assert cdt_node.generate_hash() == hash_before
    graph_acme.refresh_from_db()
    assert graph_acme.save_version == 2


@pytest.mark.django_db
def test_put_empty_object_clears_explanations(acme_client, admin_acme, cdt_node):
    response = acme_client(admin_acme).put(
        _url(cdt_node.id), {"save_version": 1, "explanations": {}}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json() == {"explanations": {}, "save_version": 2}
    cdt_node.refresh_from_db()
    assert cdt_node.metadata == {**OTHER_METADATA, "explanations": {}}


@pytest.mark.django_db
def test_put_on_node_without_metadata_creates_the_key(acme_client, admin_acme, graph_acme):
    node = ClassificationDecisionTableNode.objects.create(graph=graph_acme, node_name="bare")

    response = acme_client(admin_acme).put(
        _url(node.id), {"save_version": 1, "explanations": {"k": _explanation()}}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    node.refresh_from_db()
    assert node.metadata == {"explanations": {"k": _explanation()}}


@pytest.mark.django_db
def test_consecutive_puts_chain_save_versions(acme_client, admin_acme, cdt_node, graph_acme):
    client = acme_client(admin_acme)

    first = client.put(_url(cdt_node.id), {"save_version": 1, "explanations": {}}, format="json")
    second = client.put(
        _url(cdt_node.id),
        {"save_version": first.json()["save_version"], "explanations": {"k": _explanation()}},
        format="json",
    )

    assert second.status_code == status.HTTP_200_OK, second.content
    assert second.json()["save_version"] == 3
    graph_acme.refresh_from_db()
    assert graph_acme.save_version == 3


@pytest.mark.django_db
def test_put_strips_unknown_fields(acme_client, admin_acme, cdt_node):
    entry = {**_explanation(), "extra": "dropped"}

    response = acme_client(admin_acme).put(
        _url(cdt_node.id),
        {"save_version": 1, "explanations": {"k": entry}, "metadata": {"color": "x"}},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json()["explanations"] == {"k": _explanation()}
    cdt_node.refresh_from_db()
    assert cdt_node.metadata == {**OTHER_METADATA, "explanations": {"k": _explanation()}}


@pytest.mark.django_db
def test_put_keeps_whitespace_verbatim(acme_client, admin_acme, cdt_node):
    entry = _explanation(text="  Line one.\n\nLine two.  ", fingerprint=" fp ")

    response = acme_client(admin_acme).put(
        _url(cdt_node.id), {"save_version": 1, "explanations": {"k": entry}}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    cdt_node.refresh_from_db()
    assert cdt_node.metadata["explanations"]["k"] == entry


@pytest.mark.django_db
def test_put_accepts_values_at_every_limit(acme_client, admin_acme, cdt_node):
    explanations = {
        "k" * MAX_STEP_KEY_LENGTH: _explanation(
            text="t" * MAX_EXPLANATION_TEXT_LENGTH,
            generated_by="g" * MAX_GENERATED_BY_LENGTH,
            fingerprint="f" * MAX_FINGERPRINT_LENGTH,
        ),
        **{f"step-{index}": _explanation() for index in range(MAX_STORED_EXPLANATIONS - 1)},
    }

    response = acme_client(admin_acme).put(
        _url(cdt_node.id), {"save_version": 1, "explanations": explanations}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    cdt_node.refresh_from_db()
    assert cdt_node.metadata["explanations"] == explanations


@pytest.mark.django_db
def test_put_accepts_the_key_of_a_rule_with_a_255_character_name(
    acme_client, admin_acme, cdt_node
):
    # The frontend's longest key: `rule:name:<group_name>:manipulation`.
    step_key = f"rule:name:{'n' * 255}:manipulation"

    response = acme_client(admin_acme).put(
        _url(cdt_node.id), {"save_version": 1, "explanations": {step_key: _explanation()}}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    cdt_node.refresh_from_db()
    assert cdt_node.metadata["explanations"] == {step_key: _explanation()}


@pytest.mark.django_db
def test_put_accepts_explanations_just_under_the_total_size_cap(acme_client, admin_acme, cdt_node):
    # 52 full texts are ~1,043,400 bytes stored, under the 1,048,576 cap; 53 are over it.
    explanations = _full_texts(MAX_STORED_EXPLANATIONS_BYTES // MAX_EXPLANATION_TEXT_LENGTH)

    response = acme_client(admin_acme).put(
        _url(cdt_node.id), {"save_version": 1, "explanations": explanations}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    cdt_node.refresh_from_db()
    assert cdt_node.metadata["explanations"] == explanations


@pytest.mark.django_db
def test_member_with_flows_update_can_save(acme_client, member_only, cdt_node):
    response = acme_client(member_only).put(
        _url(cdt_node.id), {"save_version": 1, "explanations": {}}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content


# ---- versioning ----


@pytest.mark.django_db
def test_stale_save_version_returns_bulk_save_conflict_and_writes_nothing(
    acme_client, admin_acme, cdt_node, graph_acme
):
    Graph.objects.filter(pk=graph_acme.pk).update(save_version=5)
    client = acme_client(admin_acme)

    response = client.put(
        _url(cdt_node.id), {"save_version": 4, "explanations": {}}, format="json"
    )
    bulk_save_response = client.post(
        f"/api/graphs/{graph_acme.id}/save/", {"save_version": 4}, format="json"
    )

    assert response.status_code == status.HTTP_409_CONFLICT, response.content
    assert response.json() == bulk_save_response.json()
    assert response.json()["code"] == "graph_version_conflict"
    assert "current_version: 5" in response.json()["message"]
    cdt_node.refresh_from_db()
    graph_acme.refresh_from_db()
    assert cdt_node.metadata["explanations"] == {"old-step": _explanation(text="old")}
    assert graph_acme.save_version == 5


@pytest.mark.django_db
def test_notifies_open_editors_after_commit(
    acme_client, admin_acme, cdt_node, graph_acme, django_capture_on_commit_callbacks
):
    with mock.patch.object(GraphEditNotifier, "notify_graph_saved") as notify:
        with django_capture_on_commit_callbacks(execute=True):
            response = acme_client(admin_acme).put(
                _url(cdt_node.id), {"save_version": 1, "explanations": {}}, format="json"
            )

    assert response.status_code == status.HTTP_200_OK, response.content
    notify.assert_called_once()
    assert notify.call_args.kwargs["graph_id"] == graph_acme.id
    assert notify.call_args.kwargs["new_save_version"] == 2
    assert notify.call_args.kwargs["user"] == admin_acme
    assert notify.call_args.kwargs["saved_at"]


@pytest.mark.django_db
def test_conflict_notifies_nobody(
    acme_client, admin_acme, cdt_node, django_capture_on_commit_callbacks
):
    with mock.patch.object(GraphEditNotifier, "notify_graph_saved") as notify:
        with django_capture_on_commit_callbacks(execute=True):
            response = acme_client(admin_acme).put(
                _url(cdt_node.id), {"save_version": 7, "explanations": {}}, format="json"
            )

    assert response.status_code == status.HTTP_409_CONFLICT, response.content
    notify.assert_not_called()


# ---- validation ----


_LONG_KEY = "k" * (MAX_STEP_KEY_LENGTH + 1)
# Postgres jsonb cannot hold NUL, and a lone surrogate cannot be encoded to UTF-8.
_NUL_KEY = "rule:name:a\x00b:decision"
_SURROGATE_KEY = "rule:name:\ud800:decision"
_TOO_MANY = {f"step-{index}": _explanation() for index in range(MAX_STORED_EXPLANATIONS + 1)}
# Every entry is valid on its own; only the total is over the cap.
_TOO_LARGE = _full_texts(MAX_STORED_EXPLANATIONS_BYTES // MAX_EXPLANATION_TEXT_LENGTH + 1)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"explanations": {}}, id="missing-save-version"),
        pytest.param({"save_version": "one", "explanations": {}}, id="non-int-save-version"),
        pytest.param({"save_version": 1}, id="missing-explanations"),
        pytest.param({"save_version": 1, "explanations": None}, id="null-explanations"),
        pytest.param({"save_version": 1, "explanations": []}, id="list-explanations"),
        pytest.param({"save_version": 1, "explanations": "x"}, id="string-explanations"),
        pytest.param({"save_version": 1, "explanations": {"k": "text"}}, id="non-object-entry"),
        pytest.param({"save_version": 1, "explanations": {"k": None}}, id="null-entry"),
        pytest.param(
            {"save_version": 1, "explanations": {"k": {"generatedBy": "g", "fingerprint": "f"}}},
            id="missing-text",
        ),
        pytest.param(
            {"save_version": 1, "explanations": {"k": {"text": "t", "fingerprint": "f"}}},
            id="missing-generated-by",
        ),
        pytest.param(
            {"save_version": 1, "explanations": {"k": {"text": "t", "generatedBy": "g"}}},
            id="missing-fingerprint",
        ),
        pytest.param(
            {"save_version": 1, "explanations": {"k": _explanation(text=123)}},
            id="numeric-text",
        ),
        pytest.param(
            {"save_version": 1, "explanations": {"k": _explanation(fingerprint=7)}},
            id="numeric-fingerprint",
        ),
        pytest.param(
            {"save_version": 1, "explanations": {"k": _explanation(generated_by=None)}},
            id="null-generated-by",
        ),
        pytest.param(
            {"save_version": 1, "explanations": {"k": _explanation(text=["t"])}},
            id="list-text",
        ),
        pytest.param(
            {"save_version": 1, "explanations": {"k": _explanation(text="")}},
            id="blank-text",
        ),
        pytest.param(
            {"save_version": 1, "explanations": {"": _explanation()}},
            id="empty-key",
        ),
        pytest.param(
            {"save_version": 1, "explanations": {_LONG_KEY: _explanation()}},
            id="key-too-long",
        ),
        pytest.param(
            {
                "save_version": 1,
                "explanations": {
                    "k": _explanation(text="t" * (MAX_EXPLANATION_TEXT_LENGTH + 1))
                },
            },
            id="text-too-long",
        ),
        pytest.param(
            {
                "save_version": 1,
                "explanations": {
                    "k": _explanation(generated_by="g" * (MAX_GENERATED_BY_LENGTH + 1))
                },
            },
            id="generated-by-too-long",
        ),
        pytest.param(
            {
                "save_version": 1,
                "explanations": {"k": _explanation(fingerprint="f" * (MAX_FINGERPRINT_LENGTH + 1))},
            },
            id="fingerprint-too-long",
        ),
        pytest.param({"save_version": 1, "explanations": _TOO_MANY}, id="too-many-entries"),
        pytest.param({"save_version": 1, "explanations": _TOO_LARGE}, id="total-size-too-large"),
        pytest.param(
            {"save_version": 1, "explanations": {_NUL_KEY: _explanation()}}, id="nul-in-key"
        ),
        pytest.param(
            {"save_version": 1, "explanations": {_SURROGATE_KEY: _explanation()}},
            id="surrogate-in-key",
        ),
        pytest.param(
            {"save_version": 1, "explanations": {"k": _explanation(text="a\x00b")}},
            id="nul-in-text",
        ),
        pytest.param(
            {"save_version": 1, "explanations": {"k": _explanation(fingerprint="\udc80")}},
            id="surrogate-in-fingerprint",
        ),
    ],
)
@pytest.mark.django_db
def test_invalid_body_returns_400_and_writes_nothing(
    acme_client, admin_acme, cdt_node, graph_acme, body
):
    response = _send_json(acme_client(admin_acme).put, _url(cdt_node.id), body)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    _assert_untouched(cdt_node, graph_acme)


# ---- RBAC ----


@pytest.mark.django_db
def test_viewer_gets_403_and_writes_nothing(acme_client, viewer_acme, cdt_node, graph_acme):
    response = acme_client(viewer_acme).put(
        _url(cdt_node.id), {"save_version": 1, "explanations": {}}, format="json"
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    _assert_untouched(cdt_node, graph_acme)


@pytest.mark.django_db
def test_cross_org_node_returns_404_and_writes_nothing(acme_client, admin_acme, beta):
    beta_graph = Graph.objects.create(name="flow-beta", metadata={}, org=beta)
    beta_node = ClassificationDecisionTableNode.objects.create(
        graph=beta_graph, node_name="beta-cdt", metadata={"explanations": {"b": _explanation()}}
    )

    response = acme_client(admin_acme).put(
        _url(beta_node.id), {"save_version": 1, "explanations": {}}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    beta_node.refresh_from_db()
    beta_graph.refresh_from_db()
    assert beta_node.metadata == {"explanations": {"b": _explanation()}}
    assert beta_graph.save_version == 1


@pytest.mark.django_db
def test_nonexistent_node_returns_404(acme_client, admin_acme, graph_acme):
    response = acme_client(admin_acme).put(
        _url(999_999_999), {"save_version": 1, "explanations": {}}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    graph_acme.refresh_from_db()
    assert graph_acme.save_version == 1


@pytest.mark.django_db
def test_non_numeric_pk_returns_404(acme_client, admin_acme, graph_acme):
    response = acme_client(admin_acme).put(
        _url("not-a-number"), {"save_version": 1, "explanations": {}}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    graph_acme.refresh_from_db()
    assert graph_acme.save_version == 1


@pytest.mark.django_db
def test_missing_org_header_returns_400(client_as, admin_acme, cdt_node, graph_acme):
    response = client_as(admin_acme).put(
        _url(cdt_node.id), {"save_version": 1, "explanations": {}}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.json()["code"] == "org_context_required"
    _assert_untouched(cdt_node, graph_acme)


@pytest.mark.django_db
def test_soft_deleted_node_returns_404(acme_client, admin_acme, cdt_node, graph_acme):
    ClassificationDecisionTableNode.all_objects.filter(pk=cdt_node.pk).update(
        is_soft_deleted=True, soft_deleted_at=timezone.now()
    )

    response = acme_client(admin_acme).put(
        _url(cdt_node.id), {"save_version": 1, "explanations": {}}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    graph_acme.refresh_from_db()
    assert graph_acme.save_version == 1


@pytest.mark.django_db
def test_user_api_key_saves_with_its_owner_permissions(api_key_client, member_only, cdt_node):
    response = api_key_client(member_only).put(
        _url(cdt_node.id), {"save_version": 1, "explanations": {}}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_viewer_api_key_gets_403(api_key_client, viewer_acme, cdt_node, graph_acme):
    response = api_key_client(viewer_acme).put(
        _url(cdt_node.id), {"save_version": 1, "explanations": {}}, format="json"
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    _assert_untouched(cdt_node, graph_acme)


# ---- the other writer: bulk save (and node update, through the same serializer) ----


@pytest.mark.django_db
def test_bulk_save_from_before_a_put_is_a_version_conflict(
    acme_client, admin_acme, cdt_node, graph_acme
):
    client = acme_client(admin_acme)
    put = client.put(
        _url(cdt_node.id), {"save_version": 1, "explanations": {"k": _explanation()}}, format="json"
    )

    stale_bulk_save = client.post(
        _bulk_save_url(graph_acme.id),
        _bulk_save_payload(cdt_node, 1, {**OTHER_METADATA, "explanations": {}}),
        format="json",
    )

    assert put.json()["save_version"] == 2
    assert stale_bulk_save.status_code == status.HTTP_409_CONFLICT, stale_bulk_save.content
    assert stale_bulk_save.json()["code"] == "graph_version_conflict"
    cdt_node.refresh_from_db()
    graph_acme.refresh_from_db()
    assert cdt_node.metadata["explanations"] == {"k": _explanation()}
    assert graph_acme.save_version == 2


@pytest.mark.django_db
def test_bulk_save_after_a_put_writes_the_metadata_it_sends_whole(
    acme_client, admin_acme, cdt_node, graph_acme
):
    client = acme_client(admin_acme)
    client.put(
        _url(cdt_node.id), {"save_version": 1, "explanations": {"k": _explanation()}}, format="json"
    )

    response = client.post(
        _bulk_save_url(graph_acme.id), _bulk_save_payload(cdt_node, 2, OTHER_METADATA), format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    cdt_node.refresh_from_db()
    graph_acme.refresh_from_db()
    # Bulk save replaces metadata as sent, so a node sent without `explanations` loses them.
    assert cdt_node.metadata == OTHER_METADATA
    assert graph_acme.save_version == 3


@pytest.mark.django_db
def test_bulk_save_stores_explanations_in_the_frontend_metadata_shape(
    acme_client, admin_acme, cdt_node, graph_acme
):
    metadata = {
        **OTHER_METADATA,
        "explanations": {
            "node:pre": _explanation(text="Prepares the input."),
            "rule:route:approve:decision": _explanation(),
        },
    }

    response = acme_client(admin_acme).post(
        _bulk_save_url(graph_acme.id), _bulk_save_payload(cdt_node, 1, metadata), format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    cdt_node.refresh_from_db()
    assert cdt_node.metadata == metadata


_VALID = {"node:pre": _explanation(text="Prepares the input.")}


@pytest.mark.parametrize(
    ("sent", "stored"),
    [
        pytest.param(None, {}, id="null"),
        pytest.param([], {}, id="list"),
        pytest.param({**_VALID, "k": "text"}, _VALID, id="non-object-entry"),
        pytest.param({**_VALID, "k": _explanation(text=123)}, _VALID, id="numeric-text"),
        pytest.param({**_VALID, "k": _explanation(text="")}, _VALID, id="blank-text"),
        pytest.param(
            {**_VALID, "k": {"text": "t", "generatedBy": "g"}}, _VALID, id="missing-fingerprint"
        ),
        pytest.param({**_VALID, "": _explanation()}, _VALID, id="empty-key"),
        pytest.param({**_VALID, _LONG_KEY: _explanation()}, _VALID, id="key-too-long"),
        pytest.param(
            {**_VALID, "k": _explanation(text="t" * (MAX_EXPLANATION_TEXT_LENGTH + 1))},
            _VALID,
            id="text-too-long",
        ),
        pytest.param(
            {**_VALID, "k": {**_explanation(), "extra": "dropped"}},
            {**_VALID, "k": _explanation()},
            id="unknown-field",
        ),
        # Over a limit, entries are kept in step-key order until the map is full.
        pytest.param(
            _TOO_MANY,
            {key: _TOO_MANY[key] for key in sorted(_TOO_MANY)[:MAX_STORED_EXPLANATIONS]},
            id="too-many-entries",
        ),
        pytest.param(
            _TOO_LARGE,
            {key: _TOO_LARGE[key] for key in sorted(_TOO_LARGE)[:-1]},
            id="total-size-too-large",
        ),
        pytest.param({**_VALID, _NUL_KEY: _explanation()}, _VALID, id="nul-in-key"),
        pytest.param({**_VALID, _SURROGATE_KEY: _explanation()}, _VALID, id="surrogate-in-key"),
        pytest.param({**_VALID, "k": _explanation(text="a\x00b")}, _VALID, id="nul-in-text"),
        pytest.param(
            {**_VALID, "k": _explanation(generated_by="\ud800")},
            _VALID,
            id="surrogate-in-generated-by",
        ),
    ],
)
@pytest.mark.django_db
def test_bulk_save_drops_what_the_put_would_reject_and_still_saves(
    acme_client, admin_acme, cdt_node, graph_acme, sent, stored
):
    client = acme_client(admin_acme)

    response = _send_json(
        client.post,
        _bulk_save_url(graph_acme.id),
        _bulk_save_payload(cdt_node, 1, {**OTHER_METADATA, "explanations": sent}),
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    cdt_node.refresh_from_db()
    graph_acme.refresh_from_db()
    assert cdt_node.metadata == {**OTHER_METADATA, "explanations": stored}
    assert graph_acme.save_version == 2
    # The two writers agree: whatever bulk save keeps, the PUT accepts as is.
    put = client.put(_url(cdt_node.id), {"save_version": 2, "explanations": stored}, format="json")
    assert put.status_code == status.HTTP_200_OK, put.content


@pytest.mark.django_db
def test_node_update_drops_an_invalid_explanation_entry(acme_client, admin_acme, cdt_node):
    response = acme_client(admin_acme).patch(
        f"/api/classification-decision-table-node/{cdt_node.id}/",
        {"metadata": {**OTHER_METADATA, "explanations": {**_VALID, "k": _explanation(fingerprint=7)}}},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    cdt_node.refresh_from_db()
    assert cdt_node.metadata == {**OTHER_METADATA, "explanations": _VALID}


@pytest.mark.django_db
def test_dropped_explanations_are_logged_once_by_count_never_by_content(
    acme_client, admin_acme, cdt_node, graph_acme
):
    private_text = "Private wording that must not reach the log."
    sent = {**_VALID, "bad": _explanation(text=private_text, fingerprint=7)}
    messages = []
    sink_id = logger.add(messages.append, level="WARNING", format="{message}")
    try:
        response = acme_client(admin_acme).post(
            _bulk_save_url(graph_acme.id),
            _bulk_save_payload(cdt_node, 1, {**OTHER_METADATA, "explanations": sent}),
            format="json",
        )
    finally:
        logger.remove(sink_id)

    assert response.status_code == status.HTTP_200_OK, response.content
    dropped = [message.strip() for message in messages if "Dropping CDT explanations" in message]
    assert dropped == [
        f"Dropping CDT explanations (node {cdt_node.id}): 1 malformed, 0 over the limits, 1 kept"
    ]
    assert not any(private_text in message for message in messages)


@pytest.mark.django_db
def test_bulk_save_with_tens_of_thousands_of_malformed_entries_keeps_the_valid_ones(
    acme_client, admin_acme, cdt_node, graph_acme
):
    # The valid keys sort first, so they are among the entries that get examined.
    valid = {f"a-{index}": _explanation() for index in range(10)}
    malformed = {f"k-{index}": "not an object" for index in range(50_000)}

    response = _send_json(
        acme_client(admin_acme).post,
        _bulk_save_url(graph_acme.id),
        _bulk_save_payload(cdt_node, 1, {**OTHER_METADATA, "explanations": {**malformed, **valid}}),
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    cdt_node.refresh_from_db()
    assert cdt_node.metadata == {**OTHER_METADATA, "explanations": valid}
