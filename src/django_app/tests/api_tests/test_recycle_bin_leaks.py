"""Recycle-bin endpoints never let one organization see, restore or drag along another's rows.

Another org's id answers exactly like an id that doesn't exist (404, same body), a bulk
request holding one is refused whole, and a delete's batch only ever holds rows of the
org that asked for it.
"""

from unittest.mock import patch

import pytest
from django.apps import apps
from django.db.models import Max, Model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from agents.models import AgentDefinition, Surface
from rbac.models import Organization
from tables.exceptions import CrossOrgCascadeError
from tables.models import Graph, PythonCode, Secret, SourceCollection, TaskNode
from tables.models.graph_models import SubGraphNode, WebhookTriggerNode
from tables.services.cascade_org_guard import org_paths
from tables.services.secrets import secret_service
from tests.api_tests.recycle_bin_cases import AGENTS_URL, CASES, FLOWS_URL, SURFACES_URL, BinCase
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.usefixtures("retention_seven_days")

CASE_IDS = [case.key for case in CASES]
PYTHON_CODE_DATA = {"code": "def main(**kwargs): ...", "entrypoint": "main", "libraries": []}
WEBHOOK_REGISTER = "tables.signals.webhook_signals.WebhookTriggerService.register_webhooks"


def _binned(case: BinCase, org: Organization, name: str) -> Model:
    row = case.make(org, name)
    row.delete()
    return row


def _missing_pk(case: BinCase) -> int:
    highest = case.model.all_objects.aggregate(highest=Max("pk"))["highest"] or 0
    return highest + 1000


@pytest.mark.django_db
@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
class TestBulkRestoreLeaks:
    def test_only_another_orgs_id_is_404_and_it_stays_binned(self, case, acme_admin_client, beta):
        theirs = _binned(case, beta, f"Theirs {case.key}")

        response = acme_admin_client.post(f"{case.url}recycle-bin/restore/", {"ids": [theirs.pk]}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert case.model.deleted_objects.filter(pk=theirs.pk).exists()

    def test_own_and_another_orgs_id_together_restore_nothing(self, case, acme_admin_client, acme, beta):
        ours = _binned(case, acme, f"Ours {case.key}")
        theirs = _binned(case, beta, f"Theirs {case.key}")

        response = acme_admin_client.post(
            f"{case.url}recycle-bin/restore/", {"ids": [ours.pk, theirs.pk]}, format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert case.model.deleted_objects.filter(pk__in=[ours.pk, theirs.pk]).count() == 2

    def test_an_own_live_id_is_404(self, case, acme_admin_client, acme):
        live = case.make(acme, f"Live {case.key}")

        response = acme_admin_client.post(f"{case.url}recycle-bin/restore/", {"ids": [live.pk]}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert case.model.objects.filter(pk=live.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
class TestBinContentsLeaks:
    def test_another_orgs_binned_id_is_404(self, case, acme_admin_client, beta):
        theirs = _binned(case, beta, f"Theirs {case.key}")

        response = acme_admin_client.get(f"{case.url}{theirs.pk}/recycle-bin-contents/")

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content

    def test_an_own_live_id_is_404(self, case, acme_admin_client, acme):
        live = case.make(acme, f"Live {case.key}")

        response = acme_admin_client.get(f"{case.url}{live.pk}/recycle-bin-contents/")

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
class TestForeignIdLooksMissing:
    def test_restore_answers_alike_for_a_foreign_and_a_missing_id(self, case, acme_admin_client, beta):
        theirs = _binned(case, beta, f"Theirs {case.key}")

        foreign = acme_admin_client.post(f"{case.url}{theirs.pk}/restore/")
        missing = acme_admin_client.post(f"{case.url}{_missing_pk(case)}/restore/")

        assert foreign.status_code == missing.status_code == status.HTTP_404_NOT_FOUND
        assert foreign.json() == missing.json()

    def test_contents_answer_alike_for_a_foreign_and_a_missing_id(self, case, acme_admin_client, beta):
        theirs = _binned(case, beta, f"Theirs {case.key}")

        foreign = acme_admin_client.get(f"{case.url}{theirs.pk}/recycle-bin-contents/")
        missing = acme_admin_client.get(f"{case.url}{_missing_pk(case)}/recycle-bin-contents/")

        assert foreign.status_code == missing.status_code == status.HTTP_404_NOT_FOUND
        assert foreign.json() == missing.json()

    def test_bulk_restore_answers_alike_for_a_foreign_and_a_missing_id(self, case, acme_admin_client, beta):
        theirs = _binned(case, beta, f"Theirs {case.key}")
        url = f"{case.url}recycle-bin/restore/"

        foreign = acme_admin_client.post(url, {"ids": [theirs.pk]}, format="json")
        missing = acme_admin_client.post(url, {"ids": [_missing_pk(case)]}, format="json")

        assert foreign.status_code == missing.status_code == status.HTTP_404_NOT_FOUND
        assert foreign.json() == missing.json()


@pytest.mark.django_db
@pytest.mark.parametrize("case", CASES, ids=CASE_IDS)
def test_a_superadmin_restores_only_in_the_active_org(case, superadmin_in_acme, beta):
    theirs = _binned(case, beta, f"Theirs {case.key}")

    single = superadmin_in_acme.post(f"{case.url}{theirs.pk}/restore/")
    bulk = superadmin_in_acme.post(f"{case.url}recycle-bin/restore/", {"ids": [theirs.pk]}, format="json")

    assert single.status_code == status.HTTP_404_NOT_FOUND, single.content
    assert bulk.status_code == status.HTTP_404_NOT_FOUND, bulk.content
    assert case.model.deleted_objects.filter(pk=theirs.pk).exists()


@pytest.fixture
def binned_beta_secret(beta):
    secret = secret_service.create(text="sk-beta-binned", org=beta, name="BETA_BINNED")
    secret.delete()
    assert Secret.deleted_objects.filter(pk=secret.pk).exists()
    return secret


@pytest.mark.django_db
class TestAnotherOrgsBinnedSecretIsNeverLinked:
    """A binned secret the resource already uses is kept on save; another org's is an unknown pk."""

    def test_llm_config_api_key(self, use_client_6b, llm_config_pointing_at_secret_a, secret_a, binned_beta_secret):
        response = use_client_6b.patch(
            f"/api/llm-configs/{llm_config_pointing_at_secret_a.pk}/",
            {"api_key_secret_id": binned_beta_secret.pk},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "Invalid pk" in str(response.content)
        llm_config_pointing_at_secret_a.refresh_from_db()
        assert llm_config_pointing_at_secret_a.api_key_secret_id == secret_a.pk

    def test_python_tool_secret_ids(
        self, use_client_6b, python_code_tool_pointing_at_secret_a, secret_a, binned_beta_secret
    ):
        tool = python_code_tool_pointing_at_secret_a

        response = use_client_6b.patch(
            f"/api/python-code-tool/{tool.pk}/",
            {"python_code": {**PYTHON_CODE_DATA, "secret_ids": [secret_a.pk, binned_beta_secret.pk]}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "Invalid pk" in str(response.content)
        linked = set(tool.python_code.secrets(manager="all_objects").values_list("pk", flat=True))
        assert linked == {secret_a.pk}

    def test_python_node_secret_ids_through_save_flow(self, use_client_6b, default_org, secret_a, binned_beta_secret):
        graph = Graph.objects.create(name="Flow", org=default_org)
        python_code = PythonCode.objects.create(code="def main(**kwargs): ...")
        python_code.secrets.set([secret_a])
        node = WebhookTriggerNode.objects.create(graph=graph, node_name="Hook", python_code=python_code)
        entry = {
            "id": node.pk,
            "graph": graph.pk,
            "node_name": "Hook",
            "metadata": {},
            "python_code": {**PYTHON_CODE_DATA, "secret_ids": [secret_a.pk, binned_beta_secret.pk]},
            "webhook_trigger": None,
        }

        with patch(WEBHOOK_REGISTER, return_value=True):
            response = use_client_6b.post(
                reverse("graphs-save-flow", args=[graph.pk]),
                {"save_version": graph.save_version, "webhook_trigger_node_list": [entry]},
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "Invalid pk" in str(response.content)
        linked = set(python_code.secrets(manager="all_objects").values_list("pk", flat=True))
        assert linked == {secret_a.pk}


@pytest.mark.django_db
class TestCollectionBulkDelete:
    URL = "/api/source-collections/bulk-delete/"

    def test_another_orgs_collection_alone_is_left_alone(self, acme_admin_client, beta):
        theirs = SourceCollection.objects.create(org=beta, collection_name="Theirs")

        response = acme_admin_client.post(self.URL, {"collection_ids": [theirs.pk]}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["deleted_count"] == 0
        assert SourceCollection.objects.filter(pk=theirs.pk).exists()

    def test_another_orgs_collection_next_to_an_own_one_is_left_alone(self, acme_admin_client, acme, beta):
        ours = SourceCollection.objects.create(org=acme, collection_name="Ours")
        theirs = SourceCollection.objects.create(org=beta, collection_name="Theirs")

        response = acme_admin_client.post(self.URL, {"collection_ids": [ours.pk, theirs.pk]}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["deleted_count"] == 1
        assert SourceCollection.deleted_objects.filter(pk=ours.pk).exists()
        theirs_row = SourceCollection.all_objects.get(pk=theirs.pk)
        assert theirs_row.active is True
        assert theirs_row.soft_delete_batch is None


def _soft_delete_models() -> list[type[Model]]:
    return [
        model
        for model in apps.get_models()
        if any(field.name == "soft_delete_batch" for field in model._meta.concrete_fields)
    ]


def _orgs_in_batch(batch) -> dict[str, set[int | None]]:
    """Every row any soft-delete model holds in `batch`, as model name -> the orgs they belong to.

    A row's orgs are found through the owner links the cascade guard uses (org_paths); a
    row reaching no org counts as None.
    """
    orgs: dict[str, set[int | None]] = {}
    for model in _soft_delete_models():
        rows = model._base_manager.filter(soft_delete_batch=batch)
        paths = org_paths(model)
        row_values = rows.values_list(*paths) if paths else [()] * rows.count()
        for values in row_values:
            row_orgs = {value for value in values if value is not None} or {None}
            orgs.setdefault(model.__name__, set()).update(row_orgs)
    return orgs


def _binned_since(moment) -> dict[str, list[int]]:
    """Every row any soft-delete model binned at or after `moment`, as model name -> pks."""
    binned = {}
    for model in _soft_delete_models():
        pks = list(model._base_manager.filter(soft_deleted_at__gte=moment).values_list("pk", flat=True))
        if pks:
            binned[model.__name__] = pks
    return binned


def _assert_refused_as_conflict(response) -> None:
    assert response.status_code == status.HTTP_409_CONFLICT, response.content
    # Only the fixed message: no row, pk or organization the caller could learn from.
    assert response.json() == {
        "status_code": status.HTTP_409_CONFLICT,
        "code": "cross_org_cascade",
        "message": str(CrossOrgCascadeError.default_detail),
    }


@pytest.mark.django_db
class TestCascadeStaysInTheOrg:
    """The strongest cross-org links the schema can hold, written straight to the database,
    since the API refuses them (see the *_is_refused tests below). A delete that would reach
    another org's row is refused whole: nothing is binned, nulled or removed in either org."""

    def test_deleting_an_agent_that_owns_another_orgs_surface_is_refused(self, acme_admin_client, acme, beta):
        agent = AgentDefinition.objects.create(
            org=acme, name="Acme agent", instruction_list=[{"name": "Instruction_1.md", "content": "x"}]
        )
        own_surface = Surface.objects.create(org=acme, name="Acme surface", owner_agent=agent)
        foreign_surface = Surface.objects.create(org=beta, name="Beta surface", owner_agent=agent)
        before = timezone.now()

        _assert_refused_as_conflict(acme_admin_client.delete(f"{AGENTS_URL}{agent.pk}/"))

        assert AgentDefinition.objects.filter(pk=agent.pk, soft_delete_batch__isnull=True).exists()
        assert Surface.objects.filter(pk=own_surface.pk, owner_agent=agent).exists()
        assert Surface.objects.filter(pk=foreign_surface.pk, owner_agent=agent).exists()
        assert _binned_since(before) == {}

    def test_deleting_a_flow_another_orgs_subflow_node_calls_is_refused(self, acme_admin_client, acme, beta):
        acme_flow = Graph.objects.create(org=acme, name="Acme flow")
        task_node = TaskNode.objects.create(graph=acme_flow, node_name="task")
        beta_flow = Graph.objects.create(org=beta, name="Beta flow")
        beta_node = SubGraphNode.objects.create(graph=beta_flow, node_name="sub", subgraph=acme_flow)
        before = timezone.now()

        _assert_refused_as_conflict(acme_admin_client.delete(f"{FLOWS_URL}{acme_flow.pk}/"))

        assert Graph.objects.filter(pk=acme_flow.pk).exists()
        assert TaskNode.objects.filter(pk=task_node.pk).exists()
        # SET_NULL never wrote to the other org's node: it still calls the flow.
        assert SubGraphNode.objects.get(pk=beta_node.pk).subgraph_id == acme_flow.pk
        assert _binned_since(before) == {}

    def test_deleting_a_flow_an_own_subflow_node_calls_bins_only_own_rows(self, acme_admin_client, acme):
        acme_flow = Graph.objects.create(org=acme, name="Acme flow")
        TaskNode.objects.create(graph=acme_flow, node_name="task")
        caller_flow = Graph.objects.create(org=acme, name="Caller flow")
        caller_node = SubGraphNode.objects.create(graph=caller_flow, node_name="sub", subgraph=acme_flow)

        assert acme_admin_client.delete(f"{FLOWS_URL}{acme_flow.pk}/").status_code == status.HTTP_204_NO_CONTENT

        batch = Graph.all_objects.get(pk=acme_flow.pk).soft_delete_batch
        assert batch is not None
        orgs = _orgs_in_batch(batch)
        assert set(orgs) >= {"Graph", "TaskNode"}
        assert all(row_orgs == {acme.id} for row_orgs in orgs.values()), orgs
        assert SubGraphNode.objects.get(pk=caller_node.pk).subgraph_id is None

    def test_a_surface_owned_by_another_orgs_agent_is_refused(self, acme_admin_client, beta):
        theirs = AgentDefinition.objects.create(
            org=beta, name="Beta agent", instruction_list=[{"name": "Instruction_1.md", "content": "x"}]
        )

        response = acme_admin_client.post(SURFACES_URL, {"name": "Grab", "owner_agent": theirs.pk}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "Invalid pk" in str(response.content)
        assert not Surface.all_objects.filter(name="Grab").exists()

    def test_a_subgraph_node_pointing_at_another_orgs_flow_is_refused(self, acme_admin_client, acme, beta):
        ours = Graph.objects.create(org=acme, name="Ours")
        theirs = Graph.objects.create(org=beta, name="Theirs")

        response = acme_admin_client.post(
            "/api/subgraph-nodes/", {"graph": ours.pk, "node_name": "sub", "subgraph": theirs.pk}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "Invalid pk" in str(response.content)
        assert not SubGraphNode.all_objects.filter(subgraph=theirs).exists()
