"""`execution_timeout` (seconds) of the PythonCode behind every code slot of a flow node:
the python node, the webhook trigger node, and a classification decision table's pre and
post computation. Written through each node's own endpoint and through the graph bulk save.

Invariant: the stored value is a whole number of seconds, at least the minimum
(`MIN_EXECUTION_TIMEOUT_SECONDS`). Omitting it on create stores the deployment default;
omitting it on update keeps the stored value. A value above the maximum is saved as the
maximum, not rejected, because the maximum is deployment configuration that can be lowered
after a flow was built; with no maximum configured any value is kept. A value below the
minimum or not a whole number is a 400 and changes nothing.

A python code tool's `execution_timeout` is read-only: tool runs send no timeout, so a
value written through the tool endpoint is ignored and the read shows the stored one.
"""

import pytest
from django.db.models import Model
from django.urls import reverse
from rest_framework import status

from tables.models import Graph, PythonCode, PythonCodeTool
from tests.python_code_slots import PYTHON_CODE_SLOT_IDS, PYTHON_CODE_SLOTS, PythonCodeSlot

MAX_SECONDS = 600
DEFAULT_SECONDS = 45
STORED_SECONDS = 120

CODE = "def main(**kwargs): return 1"

# 2_147_483_648 does not fit the int4 column.
INVALID_TIMEOUTS = [2, 0, -5, None, 2.5, "ten", 2_147_483_648]
INVALID_TIMEOUT_IDS = ["below-minimum", "zero", "negative", "null", "fraction", "text", "above-column"]


@pytest.fixture(autouse=True)
def execution_timeout_limits(settings):
    settings.MAX_EXECUTION_TIMEOUT_SECONDS = MAX_SECONDS
    settings.DEFAULT_EXECUTION_TIMEOUT_SECONDS = DEFAULT_SECONDS


@pytest.fixture(params=PYTHON_CODE_SLOTS, ids=PYTHON_CODE_SLOT_IDS)
def slot(request) -> PythonCodeSlot:
    return request.param


@pytest.fixture
def node(slot, graph):
    python_code = PythonCode.objects.create(code=CODE, execution_timeout=STORED_SECONDS)
    return slot.create(graph, python_code)


def _python_code(**fields) -> dict:
    return {"code": CODE, "entrypoint": "main", "libraries": [], **fields}


def _create(client, slot: PythonCodeSlot, graph: Graph, python_code: dict):
    return client.post(
        reverse(f"{slot.basename}-list"), slot.request_body(graph, python_code), format="json"
    )


def _patch_code(client, slot: PythonCodeSlot, node: Model, python_code: dict):
    return client.patch(
        reverse(f"{slot.basename}-detail", args=[node.id]),
        {slot.code_field: python_code},
        format="json",
    )


def _bulk_save(client, slot: PythonCodeSlot, graph: Graph, entry: dict):
    graph.refresh_from_db()
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version, slot.graph_list_key: [entry]},
        format="json",
    )


@pytest.mark.django_db
class TestNodeEndpoint:
    def test_create_without_the_field_stores_the_default(self, auth_client, graph, slot):
        response = _create(auth_client, slot, graph, _python_code())

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert response.data[slot.code_field]["execution_timeout"] == DEFAULT_SECONDS
        assert slot.stored_timeout(response.data["id"]) == DEFAULT_SECONDS

    @pytest.mark.parametrize("seconds", [3, 90, MAX_SECONDS], ids=["minimum", "within", "maximum"])
    def test_value_round_trips(self, auth_client, graph, slot, seconds):
        create_response = _create(auth_client, slot, graph, _python_code(execution_timeout=seconds))
        assert create_response.status_code == status.HTTP_201_CREATED, create_response.content

        read_response = auth_client.get(
            reverse(f"{slot.basename}-detail", args=[create_response.data["id"]])
        )

        assert read_response.status_code == status.HTTP_200_OK, read_response.content
        assert read_response.data[slot.code_field]["execution_timeout"] == seconds
        assert slot.stored_timeout(create_response.data["id"]) == seconds

    def test_update_saves_the_new_value(self, auth_client, slot, node):
        response = _patch_code(auth_client, slot, node, _python_code(execution_timeout=30))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data[slot.code_field]["execution_timeout"] == 30
        assert slot.stored_timeout(node.id) == 30

    def test_update_without_the_field_keeps_the_stored_value(self, auth_client, slot, node):
        response = _patch_code(auth_client, slot, node, _python_code(code="def main(): return 2"))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert slot.stored_timeout(node.id) == STORED_SECONDS

    @pytest.mark.parametrize("requested", [MAX_SECONDS + 1, 10_000_000])
    def test_value_above_the_maximum_is_saved_as_the_maximum(
        self, auth_client, slot, node, requested
    ):
        response = _patch_code(auth_client, slot, node, _python_code(execution_timeout=requested))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data[slot.code_field]["execution_timeout"] == MAX_SECONDS
        assert slot.stored_timeout(node.id) == MAX_SECONDS

    def test_without_a_maximum_any_value_is_kept(self, auth_client, slot, node, settings):
        settings.MAX_EXECUTION_TIMEOUT_SECONDS = None

        response = _patch_code(auth_client, slot, node, _python_code(execution_timeout=86_400))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert slot.stored_timeout(node.id) == 86_400

    @pytest.mark.parametrize("invalid", INVALID_TIMEOUTS, ids=INVALID_TIMEOUT_IDS)
    def test_invalid_value_is_rejected_and_nothing_changes(self, auth_client, slot, node, invalid):
        response = _patch_code(auth_client, slot, node, _python_code(execution_timeout=invalid))

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "execution_timeout" in response.content.decode()
        assert slot.stored_timeout(node.id) == STORED_SECONDS


@pytest.mark.django_db
class TestBulkSave:
    def test_new_node_without_the_field_stores_the_default(self, auth_client, graph, slot):
        response = _bulk_save(auth_client, slot, graph, slot.request_body(graph, _python_code()))

        assert response.status_code == status.HTTP_200_OK, response.content
        [node] = slot.model.objects.filter(graph=graph)
        assert slot.stored_timeout(node.id) == DEFAULT_SECONDS

    @pytest.mark.parametrize(
        ("requested", "stored"),
        [(30, 30), (MAX_SECONDS + 50, MAX_SECONDS)],
        ids=["within", "above-maximum"],
    )
    def test_existing_node_saves_the_value_capped_at_the_maximum(
        self, auth_client, graph, slot, node, requested, stored
    ):
        entry = slot.request_body(graph, _python_code(execution_timeout=requested), id=node.id)

        response = _bulk_save(auth_client, slot, graph, entry)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert slot.stored_timeout(node.id) == stored

    def test_existing_node_without_the_field_keeps_the_stored_value(
        self, auth_client, graph, slot, node
    ):
        entry = slot.request_body(graph, _python_code(code="def main(): return 2"), id=node.id)

        response = _bulk_save(auth_client, slot, graph, entry)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert slot.stored_timeout(node.id) == STORED_SECONDS

    @pytest.mark.parametrize("invalid", INVALID_TIMEOUTS, ids=INVALID_TIMEOUT_IDS)
    def test_invalid_value_is_rejected_and_nothing_changes(
        self, auth_client, graph, slot, node, invalid
    ):
        entry = slot.request_body(graph, _python_code(execution_timeout=invalid), id=node.id)

        response = _bulk_save(auth_client, slot, graph, entry)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "execution_timeout" in response.content.decode()
        assert slot.stored_timeout(node.id) == STORED_SECONDS


@pytest.mark.django_db
def test_graph_read_returns_the_stored_value(auth_client, graph, slot, node):
    response = auth_client.get(reverse("graphs-detail", args=[graph.id]))

    assert response.status_code == status.HTTP_200_OK, response.content
    [node_data] = response.data[slot.graph_list_key]
    assert node_data[slot.code_field]["execution_timeout"] == STORED_SECONDS


@pytest.mark.django_db
class TestPythonCodeToolEndpoint:
    def test_create_ignores_the_field_and_stores_the_default(self, auth_client):
        response = auth_client.post(
            reverse("pythoncodetool-list"),
            {
                "name": "timeout-tool",
                "description": "tool",
                "python_code": _python_code(execution_timeout=90),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert response.data["python_code"]["execution_timeout"] == DEFAULT_SECONDS
        tool = PythonCodeTool.objects.get(pk=response.data["id"])
        assert tool.python_code.execution_timeout == DEFAULT_SECONDS

    def test_update_ignores_the_field(self, auth_client, default_org):
        tool = PythonCodeTool.objects.create(
            name="timeout-tool",
            description="tool",
            org=default_org,
            python_code=PythonCode.objects.create(code=CODE, execution_timeout=STORED_SECONDS),
        )

        response = auth_client.patch(
            reverse("pythoncodetool-detail", args=[tool.id]),
            {"python_code": _python_code(execution_timeout=30)},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["python_code"]["execution_timeout"] == STORED_SECONDS
        tool.python_code.refresh_from_db()
        assert tool.python_code.execution_timeout == STORED_SECONDS
