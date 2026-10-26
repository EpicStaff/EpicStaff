"""The service-account principal asks the database once per secret it confirms as the plugin's own."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from tables.models import Graph, PythonCode, Secret
from tables.models.graph_models import PythonNode
from tables.services.secrets import secret_service

from tests.plugins_tests.conftest import GATEWAY_SECRET, service_account_client

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("service_account_platform")]


@pytest.fixture
def acme_key(weather_backend, service_account_key, acme):
    return service_account_key(weather_backend(), acme)


@pytest.fixture
def client(acme_key, acme):
    return service_account_client(acme_key, acme)


def _principal(raw_key):
    request = Request(
        APIRequestFactory().get(
            "/api/graphs/", HTTP_AUTHORIZATION=f"PluginKey {raw_key}", HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET
        ),
        authenticators=[PluginServiceAccountAuthentication()],
    )
    return request.user


def _own_secret(client, name):
    response = client.post("/api/secrets/", {"name": name, "value": "sk-weather"}, format="json")
    assert response.status_code == 201, response.content
    return Secret.objects.get(pk=response.json()["id"])


def _ownership_lookups(captured):
    return [
        query["sql"]
        for query in captured.captured_queries
        if query["sql"].startswith("SELECT") and '"plugins_pluginownedresource"."object_id" IN' in query["sql"]
    ]


def test_a_confirmed_secret_is_not_asked_about_again(client, acme_key):
    key = _own_secret(client, "Weather key")
    principal = _principal(acme_key)

    with CaptureQueriesContext(connection) as first:
        assert principal.may_reference_secrets(frozenset({key.pk}))
    with CaptureQueriesContext(connection) as again:
        assert principal.may_reference_secrets(frozenset({key.pk}))

    assert (len(_ownership_lookups(first)), len(again.captured_queries)) == (1, 0)


def test_only_the_secrets_not_yet_confirmed_are_asked_about(client, acme_key):
    first, second = _own_secret(client, "Weather key"), _own_secret(client, "Weather backup key")
    principal = _principal(acme_key)
    principal.may_reference_secrets(frozenset({first.pk}))

    with CaptureQueriesContext(connection) as captured:
        assert principal.may_reference_secrets(frozenset({first.pk, second.pk}))

    [lookup] = _ownership_lookups(captured)
    assert f"IN ({second.pk})" in lookup


def test_a_refused_secret_is_asked_about_again_and_stays_refused(client, acme_key, acme):
    own = _own_secret(client, "Weather key")
    organization_s = secret_service.create(text="sk-acme", org=acme, name="Acme key")
    principal = _principal(acme_key)

    assert not principal.may_reference_secrets(frozenset({own.pk, organization_s.pk}))
    with CaptureQueriesContext(connection) as captured:
        assert not principal.may_reference_secrets(frozenset({organization_s.pk}))

    assert len(_ownership_lookups(captured)) == 1
    assert principal.may_reference_secrets(frozenset({own.pk}))


def test_each_request_has_its_own_principal_and_asks_again(client, acme_key):
    key = _own_secret(client, "Weather key")
    _principal(acme_key).may_reference_secrets(frozenset({key.pk}))

    with CaptureQueriesContext(connection) as captured:
        assert _principal(acme_key).may_reference_secrets(frozenset({key.pk}))

    assert len(_ownership_lookups(captured)) == 1


def test_no_secrets_need_no_query(acme_key):
    with CaptureQueriesContext(connection) as captured:
        assert _principal(acme_key).may_reference_secrets(frozenset())

    assert _ownership_lookups(captured) == []


def test_the_principal_no_longer_answers_whether_it_owns_a_row(acme_key):
    assert not hasattr(_principal(acme_key), "owns")


NEUTRAL_CODE = "def main(**kwargs):\n    return 1\n"


def test_a_bulk_save_of_ten_python_nodes_using_one_own_secret_costs_one_ownership_query(client):
    key = _own_secret(client, "Weather key")
    graph = Graph.objects.get(pk=client.post("/api/graphs/", {"name": "Weather flow"}, format="json").json()["id"])
    nodes = []
    for index in range(10):
        python_code = PythonCode.objects.create(code=NEUTRAL_CODE, entrypoint="main")
        python_code.secrets.add(key)
        nodes.append(PythonNode.objects.create(graph=graph, node_name=f"node_{index}", python_code=python_code))
    graph.refresh_from_db()
    body = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "id": node.pk,
                "graph": graph.pk,
                "node_name": node.node_name,
                "python_code": {
                    "code": "def main(**kwargs):\n    return 2\n",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "secret_ids": [key.pk],
                },
            }
            for node in nodes
        ],
    }

    with CaptureQueriesContext(connection) as captured:
        response = client.post(f"/api/graphs/{graph.pk}/save/", body, format="json")

    assert response.status_code == 200, response.content
    assert len(_ownership_lookups(captured)) == 1
