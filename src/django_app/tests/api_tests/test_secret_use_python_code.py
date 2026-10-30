"""Editing or copying Python code that declares secrets needs secrets:USE.

The declared secrets are handed to the code at run time, so whoever rewrites or
copies (and so owns) that code decides what is done with their plaintext. Code
that declares none is edited and copied freely, and a bulk save that resends a
node's code unchanged needs no permission.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from proxies.sandbox.models import SandboxVenvBinding
from rest_framework.test import APIClient

from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.models import PythonCode, PythonCodeTool
from tables.exceptions import CodeWithSecretsRequiresSecretsUsePermissionError
from tables.exceptions import FlowWithTriggerNodesRequiresUsePermissionError
from tables.models import WebhookTrigger
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    Graph,
    PythonNode,
    ScheduleTriggerNode,
    WebhookTriggerNode,
)
from tables.services.copy_services import GraphCopyService
from tables.services.copy_services.helpers import copy_python_code
from tables.services.secrets import secret_service
from tables.services.secrets.secret_use_service import SecretActor
from tests.rbac_cross_org_fixtures import acme  # noqa: F401  -- fixture

REFUSAL_CODE = CodeWithSecretsRequiresSecretsUsePermissionError.default_code
CODE = 'def main(**kwargs):\n    return get_secret("PY_KEY")\n'
OTHER_CODE = 'def main(**kwargs):\n    return get_secret("PY_KEY") + "!"\n'
WRITE = int(Permission.CREATE | Permission.READ | Permission.UPDATE)


def _client(*, org, django_user_model, email, secrets_bitmask, flows_bitmask=WRITE):
    """An APIClient for a new user of `org`; the user is on `client.user`."""
    role = Role.objects.create(name=f"role-{email}", org=org, is_built_in=False)
    for resource_type, bitmask in (
        (ResourceType.SECRETS, secrets_bitmask),
        (ResourceType.FLOWS, flows_bitmask),
        (ResourceType.TOOLS, WRITE),
    ):
        RolePermission.objects.create(
            role=role, resource_type=resource_type.value, permissions=bitmask
        )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    client.user = user
    return client


@pytest.fixture
def no_use_client(django_user_model, acme):
    return _client(
        org=acme,
        django_user_model=django_user_model,
        email="pycode-nouse@example.com",
        secrets_bitmask=int(Permission.READ),
    )


@pytest.fixture
def runner_no_use_client(django_user_model, acme):
    """Holds flows:USE, so copying trigger nodes is allowed, but only READ on secrets."""
    return _client(
        org=acme,
        django_user_model=django_user_model,
        email="pycode-runner-nouse@example.com",
        secrets_bitmask=int(Permission.READ),
        flows_bitmask=WRITE | int(Permission.USE),
    )


@pytest.fixture
def use_client(django_user_model, acme):
    return _client(
        org=acme,
        django_user_model=django_user_model,
        email="pycode-use@example.com",
        secrets_bitmask=int(Permission.READ | Permission.USE),
    )


@pytest.fixture
def secret(acme):
    return secret_service.create(text="sk-pycode", org=acme, name="PY_KEY")


@pytest.fixture
def venv(acme):
    return SandboxVenvBinding.objects.create(org_id=acme.id, resource_id="4711")


@pytest.fixture
def graph(acme):
    return Graph.objects.create(name="Secret code flow", org=acme)


def _declaring_code(secret):
    python_code = PythonCode.objects.create(code=CODE, entrypoint="main")
    python_code.secrets.set([secret])
    return python_code


@pytest.fixture
def declaring_node(graph, secret):
    return PythonNode.objects.create(
        graph=graph, node_name="declarer", python_code=_declaring_code(secret)
    )


@pytest.fixture
def declaring_tool(acme, secret):
    return PythonCodeTool.objects.create(
        name="Declaring tool",
        description="reads a secret",
        python_code=_declaring_code(secret),
        org=acme,
    )


#: (sent python_code fields, field the denial names) for each field that decides what the code runs.
CODE_CHANGES = [
    pytest.param({"code": OTHER_CODE}, "code", id="code"),
    pytest.param({"entrypoint": "other"}, "entrypoint", id="entrypoint"),
    pytest.param("venv", "venv_id", id="venv_id"),
    pytest.param({"global_kwargs": {"target": "https://elsewhere.example"}}, "global_kwargs", id="global_kwargs"),
]


def _change(change, venv):
    return {"venv_id": venv.pk} if change == "venv" else change


def _snapshot(python_code):
    python_code.refresh_from_db()
    return (python_code.code, python_code.entrypoint, python_code.venv_id, python_code.global_kwargs)


@pytest.mark.django_db
class TestEditingDeclaringCode:
    @pytest.mark.parametrize("change,field_name", CODE_CHANGES)
    def test_a_node_edit_without_use_is_refused_under_the_changed_field(
        self, no_use_client, declaring_node, venv, change, field_name
    ):
        before = _snapshot(declaring_node.python_code)

        response = no_use_client.patch(
            f"/api/pythonnodes/{declaring_node.id}/",
            {"python_code": _change(change, venv)},
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert response.json()["message"].startswith(f"python_code: {field_name}: ")
        assert "Changing code that reads secrets" in response.json()["message"]
        assert _snapshot(declaring_node.python_code) == before

    @pytest.mark.parametrize("change,field_name", CODE_CHANGES)
    def test_a_node_edit_with_use_is_saved(
        self, use_client, declaring_node, venv, change, field_name
    ):
        response = use_client.patch(
            f"/api/pythonnodes/{declaring_node.id}/",
            {"python_code": _change(change, venv)},
            format="json",
        )

        assert response.status_code == 200, response.json()
        sent = _change(change, venv)[field_name]
        stored = response.json()["python_code"][field_name]
        assert stored == (sent.strip() if isinstance(sent, str) else sent)

    def test_a_tool_code_edit_without_use_is_refused(self, no_use_client, declaring_tool):
        response = no_use_client.patch(
            f"/api/python-code-tool/{declaring_tool.id}/",
            {"python_code": {"code": OTHER_CODE}},
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert response.json()["message"].startswith("python_code: code: ")
        declaring_tool.python_code.refresh_from_db()
        assert declaring_tool.python_code.code == CODE

    def test_a_tool_code_edit_with_use_is_saved(self, use_client, declaring_tool):
        response = use_client.patch(
            f"/api/python-code-tool/{declaring_tool.id}/",
            {"python_code": {"code": OTHER_CODE}},
            format="json",
        )

        assert response.status_code == 200, response.json()
        declaring_tool.python_code.refresh_from_db()
        assert declaring_tool.python_code.code == OTHER_CODE.strip()

    def test_resending_the_same_code_without_use_is_accepted(
        self, no_use_client, declaring_node, secret
    ):
        response = no_use_client.patch(
            f"/api/pythonnodes/{declaring_node.id}/",
            {
                "node_name": "renamed",
                "python_code": {
                    "code": CODE,
                    "entrypoint": "main",
                    "venv_id": None,
                    "global_kwargs": {},
                    "secret_ids": [secret.id],
                },
            },
            format="json",
        )

        assert response.status_code == 200, response.json()
        declaring_node.refresh_from_db()
        assert declaring_node.node_name == "renamed"

    def test_a_binned_declared_secret_still_gates_the_code(
        self, no_use_client, declaring_node, secret
    ):
        """A binned secret stays linked until purged, and comes back readable on restore."""
        secret.delete()

        response = no_use_client.patch(
            f"/api/pythonnodes/{declaring_node.id}/",
            {"python_code": {"code": "def main(**kwargs):\n    return 2\n"}},
            format="json",
        )

        assert response.status_code == 400, response.json()

    def test_code_that_declares_nothing_is_edited_without_use(self, no_use_client, graph):
        node = PythonNode.objects.create(
            graph=graph,
            node_name="plain",
            python_code=PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n"),
        )

        response = no_use_client.patch(
            f"/api/pythonnodes/{node.id}/",
            {"python_code": {"code": "def main(**kwargs):\n    return 2\n"}},
            format="json",
        )

        assert response.status_code == 200, response.json()

    def test_dropping_the_declaration_with_the_code_still_needs_use(
        self, no_use_client, declaring_node
    ):
        """Clearing the declared secrets is a change of the set, which needs USE on its own."""
        response = no_use_client.patch(
            f"/api/pythonnodes/{declaring_node.id}/",
            {"python_code": {"code": "def main(**kwargs):\n    return 1\n", "secret_ids": []}},
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert response.json()["message"].startswith("python_code: secret_ids: ")

    def test_creating_code_that_declares_a_secret_without_use_is_refused(
        self, no_use_client, graph, secret
    ):
        response = no_use_client.post(
            "/api/pythonnodes/",
            {
                "graph": graph.id,
                "node_name": "new declarer",
                "python_code": {"code": CODE, "entrypoint": "main", "secret_ids": [secret.id]},
            },
            format="json",
        )

        assert response.status_code == 400, response.json()
        assert not PythonNode.objects.filter(node_name="new declarer").exists()


def _bulk_node(graph, node, **python_code_changes):
    """One node of a bulk save, resending its stored code with `python_code_changes` applied."""
    python_code = node.python_code
    return {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "id": node.id,
                "graph": graph.id,
                "node_name": "moved and renamed",
                "metadata": {"position": {"x": 300, "y": 120}},
                "python_code": {
                    "code": python_code.code,
                    "entrypoint": python_code.entrypoint,
                    "venv_id": python_code.venv_id,
                    "global_kwargs": python_code.global_kwargs,
                    **python_code_changes,
                },
            }
        ],
    }


@pytest.mark.django_db
class TestBulkSavingDeclaringCode:
    def test_moving_and_renaming_without_use_is_accepted(
        self, no_use_client, graph, declaring_node
    ):
        response = no_use_client.post(
            f"/api/graphs/{graph.id}/save/", _bulk_node(graph, declaring_node), format="json"
        )

        assert response.status_code == 200, response.json()
        declaring_node.refresh_from_db()
        assert declaring_node.node_name == "moved and renamed"

    def test_a_code_change_without_use_is_refused_on_that_node(
        self, no_use_client, graph, declaring_node
    ):
        response = no_use_client.post(
            f"/api/graphs/{graph.id}/save/",
            _bulk_node(graph, declaring_node, code=OTHER_CODE),
            format="json",
        )

        assert response.status_code == 400, response.json()
        [item] = response.json()["errors"]["python_node_list"]
        assert item["index"] == 0
        [message] = item["errors"]["python_code"]["code"]
        assert '"Use" permission on Secrets' in message
        declaring_node.refresh_from_db()
        assert (declaring_node.node_name, _snapshot(declaring_node.python_code)[0]) == (
            "declarer",
            CODE,
        )

    def test_a_code_change_with_use_is_saved(self, use_client, graph, declaring_node):
        response = use_client.post(
            f"/api/graphs/{graph.id}/save/",
            _bulk_node(graph, declaring_node, code=OTHER_CODE),
            format="json",
        )

        assert response.status_code == 200, response.json()
        declaring_node.refresh_from_db()
        assert declaring_node.python_code.code == OTHER_CODE.strip()


@pytest.mark.django_db
class TestCopyingDeclaringCode:
    def test_a_tool_copy_without_use_is_refused_and_writes_nothing(
        self, no_use_client, declaring_tool
    ):
        tools_before = PythonCodeTool.objects.count()
        codes_before = PythonCode.objects.count()

        response = no_use_client.post(f"/api/python-code-tool/{declaring_tool.id}/copy/")

        assert response.status_code == 403, response.json()
        assert response.json()["code"] == REFUSAL_CODE
        assert PythonCodeTool.objects.count() == tools_before
        assert PythonCode.objects.count() == codes_before

    def test_a_tool_copy_with_use_keeps_the_declaration(
        self, use_client, declaring_tool, secret
    ):
        response = use_client.post(f"/api/python-code-tool/{declaring_tool.id}/copy/")

        assert response.status_code == 201, response.json()
        copied = PythonCodeTool.objects.get(pk=response.json()["id"])
        assert list(copied.python_code.secrets.values_list("pk", flat=True)) == [secret.pk]

    def test_a_flow_copy_without_use_is_refused_and_leaves_nothing_behind(
        self, no_use_client, graph, declaring_node
    ):
        """One declaring node refuses the whole copy: no graph, node or code is left."""
        PythonNode.objects.create(
            graph=graph,
            node_name="plain",
            python_code=PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n"),
        )
        graphs_before = set(Graph.all_objects.values_list("pk", flat=True))
        nodes_before = PythonNode.objects.count()
        codes_before = PythonCode.objects.count()

        response = no_use_client.post(f"/api/graphs/{graph.id}/copy/")

        assert response.status_code == 403, response.json()
        assert response.json()["code"] == REFUSAL_CODE
        assert set(Graph.all_objects.values_list("pk", flat=True)) == graphs_before
        assert PythonNode.objects.count() == nodes_before
        assert PythonCode.objects.count() == codes_before

    def test_a_flow_copy_with_use_keeps_the_declaration(
        self, use_client, graph, declaring_node, secret
    ):
        response = use_client.post(f"/api/graphs/{graph.id}/copy/")

        assert response.status_code == 201, response.json()
        copied_node = PythonNode.objects.get(graph_id=response.json()["id"])
        assert list(copied_node.python_code.secrets.values_list("pk", flat=True)) == [secret.pk]

    def test_a_flow_without_declarations_is_copied_without_use(self, no_use_client, graph):
        PythonNode.objects.create(
            graph=graph,
            node_name="plain",
            python_code=PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n"),
        )

        response = no_use_client.post(f"/api/graphs/{graph.id}/copy/")

        assert response.status_code == 201, response.json()

    def test_copy_python_code_refuses_an_actor_without_use_before_writing(
        self, acme, no_use_client, declaring_node
    ):
        """The backstop every copy passes through, whatever endpoint started it."""
        codes_before = PythonCode.objects.count()

        with pytest.raises(CodeWithSecretsRequiresSecretsUsePermissionError):
            copy_python_code(
                declaring_node.python_code,
                actor=SecretActor.for_user(no_use_client.user, acme.id),
            )

        assert PythonCode.objects.count() == codes_before

    def test_the_graph_copy_service_rolls_itself_back(self, no_use_client, graph, declaring_node):
        """Called without the endpoint's pre-check, the copy refuses at the node and owns its rollback."""
        graphs_before = set(Graph.all_objects.values_list("pk", flat=True))
        codes_before = PythonCode.objects.count()

        with pytest.raises(CodeWithSecretsRequiresSecretsUsePermissionError):
            GraphCopyService().copy(graph, user=no_use_client.user)

        assert set(Graph.all_objects.values_list("pk", flat=True)) == graphs_before
        assert PythonCode.objects.count() == codes_before

    @pytest.mark.parametrize(
        "add_only_declaring_code",
        [
            pytest.param(
                lambda graph, secret: WebhookTriggerNode.objects.create(
                    graph=graph,
                    node_name="Incoming",
                    webhook_trigger=WebhookTrigger.objects.create(path="copy-hook", org=graph.org),
                    python_code=_declaring_code(secret),
                ),
                id="webhook-trigger-node",
            ),
            pytest.param(
                lambda graph, secret: ClassificationDecisionTableNode.objects.create(
                    graph=graph, node_name="classify", pre_python_code=_declaring_code(secret)
                ),
                id="cdt-pre-code",
            ),
        ],
    )
    def test_a_flow_whose_only_declaring_code_is_another_site_is_refused(
        self, runner_no_use_client, graph, secret, add_only_declaring_code
    ):
        add_only_declaring_code(graph, secret)
        graphs_before = set(Graph.all_objects.values_list("pk", flat=True))
        codes_before = PythonCode.objects.count()

        response = runner_no_use_client.post(f"/api/graphs/{graph.id}/copy/")

        assert response.status_code == 403, response.json()
        assert response.json()["code"] == REFUSAL_CODE
        assert set(Graph.all_objects.values_list("pk", flat=True)) == graphs_before
        assert PythonCode.objects.count() == codes_before

    def test_the_trigger_refusal_wins_when_both_apply(self, no_use_client, graph, declaring_node):
        ScheduleTriggerNode.objects.create(graph=graph, node_name="Hourly")

        response = no_use_client.post(f"/api/graphs/{graph.id}/copy/")

        assert response.status_code == 403, response.json()
        assert (
            response.json()["code"]
            == FlowWithTriggerNodesRequiresUsePermissionError.default_code
        )


def _declaring_nodes_flow(graph, secret, count: int) -> list[PythonNode]:
    return [
        PythonNode.objects.create(
            graph=graph, node_name=f"declarer-{index}", python_code=_declaring_code(secret)
        )
        for index in range(count)
    ]


def _rename_payload(graph, nodes, secret) -> dict:
    """A bulk save of `nodes` renamed, their code and `secret_ids` resent unchanged, as the editor does."""
    graph.refresh_from_db()
    items = []
    for node in nodes:
        item = _bulk_node(graph, node)["python_node_list"][0]
        item["node_name"] = f"{node.node_name}-moved"
        item["python_code"]["secret_ids"] = [secret.id]
        items.append(item)
    return {"save_version": graph.save_version, "python_node_list": items}


def _queries_to_rename(client, graph, nodes, secret) -> int:
    payload = _rename_payload(graph, nodes, secret)
    with CaptureQueriesContext(connection) as captured:
        response = client.post(f"/api/graphs/{graph.id}/save/", payload, format="json")
    assert response.status_code == 200, response.json()
    return len(captured.captured_queries)


# What saving one more renamed node costs: the same per-node validation, write and
# last-edit tracking as `MAX_QUERIES_PER_CHANGED_PYTHON_NODE` in
# bulk_save_test/test_bulk_save_last_edit.py. The secret Use check adds none, as the
# bulk save prefetches each node's code and links; reading them per node costs 15.
MAX_QUERIES_PER_RENAMED_DECLARING_NODE = 12


@pytest.mark.django_db
def test_bulk_saving_declaring_nodes_costs_a_fixed_number_of_queries_each(
    no_use_client, acme, secret, django_assert_max_num_queries
):
    def flow_of(count):
        graph = Graph.objects.create(name=f"budget-{count}-{Graph.objects.count()}", org=acme)
        return graph, _declaring_nodes_flow(graph, secret, count)

    # Content type lookups are cached per process after the first save.
    _queries_to_rename(no_use_client, *flow_of(1), secret)
    one_node_queries = _queries_to_rename(no_use_client, *flow_of(1), secret)
    graph, nodes = flow_of(5)
    payload = _rename_payload(graph, nodes, secret)

    with django_assert_max_num_queries(
        one_node_queries + 4 * MAX_QUERIES_PER_RENAMED_DECLARING_NODE
    ):
        response = no_use_client.post(f"/api/graphs/{graph.id}/save/", payload, format="json")

    assert response.status_code == 200, response.json()
