"""A flow run by a plugin's service account records the plugin, and the person it ran for."""

import csv
import io
import uuid

import fakeredis
import pytest
from django.urls import reverse
from django.utils import timezone
from tables.import_export.enums import EntityType
from tables.import_export.export_format_strategies import CsvExportFormatStrategy
from tables.import_export.export_tabular_projections.session import SessionTabularProjection
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import Graph, Session
from tables.models.graph_models import GraphSessionMessage
from tables.models.session_models import SessionPrincipal
from tables.services.graph_message_store import GraphMessageStore

from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.plugins_tests.conftest import service_account_client
from tests.plugins_tests.service_account_helpers import runnable_graph

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def weather(weather_backend):
    return weather_backend()


@pytest.fixture
def forecast_graph(acme):
    return runnable_graph("Weather forecast", acme)


def _run(client, graph):
    response = client.post(reverse("run-session"), {"graph_id": graph.pk, "variables": {}}, format="json")
    assert response.status_code == 201, response.content
    return Session.objects.get(pk=response.json()["session_id"])


def _add_message(session, **message_data):
    GraphSessionMessage.objects.create(
        session=session,
        created_at=timezone.now(),
        name="n1",
        execution_order=0,
        message_data={"message_type": "finish", **message_data},
        uuid=uuid.uuid4(),
    )


def _csv_rows(session):
    data = ExportService(entity_registry).export_entities(
        EntityType.SESSION, [session.pk], policy=UNRESTRICTED_EXPORT_POLICY
    ).data
    response = CsvExportFormatStrategy(SessionTabularProjection()).render(data, EntityType.SESSION, "session", str(session.pk))
    return list(csv.DictReader(io.StringIO(response.content.decode())))


def test_a_run_on_behalf_of_a_person_records_the_plugin_and_the_person(
    weather, service_account_key, acme, member_only, forecast_graph, redis_client_mock, client_as, admin_acme
):
    client = service_account_client(service_account_key(weather, acme), acme, on_behalf_of=member_only.pk)

    session = _run(client, forecast_graph)

    principal = session.principal
    assert (principal.kind, principal.plugin_identifier) == (SessionPrincipal.ActionKind.PLUGIN, "weather")
    assert (principal.user_id, principal.email, principal.api_key_id) == (member_only.pk, member_only.email, None)
    assert session.graph_user.organization_user.user_id == member_only.pk
    reader = client_as(admin_acme)
    reader.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))
    assert reader.get(f"/api/sessions/{session.pk}/").json()["principal"] == {
        "kind": "plugin",
        "user": member_only.pk,
        "api_key": None,
        "email": member_only.email,
        "plugin_identifier": "weather",
    }


def test_a_run_of_the_plugin_on_its_own_names_no_person(weather, service_account_key, acme, forecast_graph, redis_client_mock):
    session = _run(service_account_client(service_account_key(weather, acme), acme), forecast_graph)

    principal = session.principal
    assert (principal.kind, principal.plugin_identifier, principal.user_id, principal.email) == (
        SessionPrincipal.ActionKind.PLUGIN,
        "weather",
        None,
        None,
    )
    assert session.graph_user is None


def test_subflow_sessions_keep_the_plugin(weather, service_account_key, acme, member_only, forecast_graph, redis_client_mock):
    client = service_account_client(service_account_key(weather, acme), acme, on_behalf_of=member_only.pk)
    root = _run(client, forecast_graph)
    child_graph = Graph.objects.create(name="Child", org=acme)
    for message_type, extra in (
        ("subgraph_start", {"subgraph_id": child_graph.pk, "input": {}, "subgraph_execution_ids": []}),
        ("subgraph_finish", {"output": {}}),
    ):
        GraphSessionMessage.objects.create(
            session=root,
            created_at=timezone.now(),
            message_data={"message_type": message_type, "subgraph_execution_id": "exec-plugin", **extra},
            uuid=uuid.uuid4(),
        )

    GraphMessageStore(fakeredis.FakeRedis()).create_subgraph_sessions(root.pk)

    child = Session.objects.get(parent_session=root).principal
    assert (child.kind, child.plugin_identifier, child.user_id) == (SessionPrincipal.ActionKind.PLUGIN, "weather", member_only.pk)


def test_the_tabular_export_names_the_plugin_and_the_person(
    weather, service_account_key, acme, member_only, forecast_graph, redis_client_mock
):
    on_behalf = _run(service_account_client(service_account_key(weather, acme), acme, on_behalf_of=member_only.pk), forecast_graph)
    on_its_own = _run(service_account_client(service_account_key(weather, acme), acme), forecast_graph)
    for session in (on_behalf, on_its_own):
        _add_message(session)

    [with_person] = _csv_rows(on_behalf)
    [without_person] = _csv_rows(on_its_own)

    assert (with_person["started_by_type"], with_person["started_by"]) == ("plugin", f"weather (plugin) on behalf of {member_only.email}")
    assert (without_person["started_by_type"], without_person["started_by"]) == ("plugin", "weather (plugin)")
