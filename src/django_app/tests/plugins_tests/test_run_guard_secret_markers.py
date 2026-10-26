"""A run a plugin starts sends no secret the plugin may not reference through a header marker.

An `epicstaff_secret(<name>)` marker binds by name when the run starts. The plugin wrote the
name while it meant a secret of its own; by the time it runs, the name may mean a person's
secret (the plugin's purged, and a person's created under the same name). The run guard asks
the write-time rule again at the start, for runs and for indexing jobs the plugin starts.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from plugins.identity.service_account_authentication import PluginServiceAccountAuthentication
from plugins.models import PluginGrant
from plugins.ownership.request_scope import request_scope
from plugins.runs.run_guard import PluginRunGuard
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from tables.models import EmbeddingConfig, Session
from tables.models.graph_models import ClassificationDecisionTableNode, ClassificationDecisionTablePrompt
from tables.models.knowledge_models.collection_models import BaseRagType, DocumentMetadata, SourceCollection
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.services.run_admission import RunKind, RunSubject, assert_run_admitted, assert_still_admitted
from tables.services.secrets.exceptions import SecretMarkerNotReferenceableError

from tests.plugins_tests.conftest import GATEWAY_SECRET, service_account_client
from tests.plugins_tests.suspension_helpers import flow, llm_config, marker, own, secret_row

pytestmark = [pytest.mark.django_db]

KEY_NAME = "Weather gateway key"
REFUSAL = {
    "status_code": 409,
    "code": "secret_marker_not_referenceable",
    "message": (
        "This credential can reference only secrets it created, but a model configuration used here "
        "names another secret in a header, so this cannot start."
    ),
}
ACCESS = [
    {"resource_type": "flows", "actions": ["read", "create", "update", "use"], "reason": "Runs the forecast flow."},
    {"resource_type": "secrets", "actions": ["read", "create", "use"], "reason": "Stores its gateway key."},
    {"resource_type": "llm_configs", "actions": ["read", "create", "update"], "reason": "Its LLM configs."},
    {"resource_type": "knowledge_sources", "actions": ["read", "create", "update"], "reason": "Indexes forecasts."},
]


@pytest.fixture
def plugin(weather_backend):
    return weather_backend(access=ACCESS)


@pytest.fixture
def acme_key(plugin, service_account_key, acme):
    return service_account_key(plugin, acme)


@pytest.fixture
def grant(plugin, acme, acme_key):
    return PluginGrant.objects.get(plugin=plugin, org=acme)


@pytest.fixture
def own_key(grant, acme):
    """The plugin's gateway key, recorded as the plugin's own."""
    secret = secret_row(acme, KEY_NAME)
    own(secret, grant)
    return secret


def _forecast_flow(acme, headers):
    graph = flow(acme, "Weather forecast")
    config = llm_config(acme, "Weather classifier", extra_headers=headers)
    ClassificationDecisionTableNode.objects.create(graph=graph, node_name="cdt", default_llm_config=config)
    return graph


def _subject(graph) -> RunSubject:
    return RunSubject(RunKind.FLOW, graph.pk, graph.org_id)


@contextmanager
def _started_by(raw_key):
    """Inside, the plugin's service account is the current request's principal, as when it calls."""
    request = Request(
        APIRequestFactory().post(
            "/api/run-session/", HTTP_AUTHORIZATION=f"PluginKey {raw_key}", HTTP_X_PLUGIN_NETWORK_SECRET=GATEWAY_SECRET
        ),
        authenticators=[PluginServiceAccountAuthentication()],
    )
    with request_scope() as scope:
        # Authenticating fills the scope's principal.
        assert request.user is scope.principal
        yield scope


def _purge_and_recreate(secret):
    """The plugin's secret binned and purged, and a person's created under its name."""
    secret.soft_delete()
    secret.purge()
    return secret_row(secret.org, secret.name)


# ---- runs ----


def test_a_plugin_runs_a_flow_whose_header_marker_names_its_own_secret(acme, acme_key, own_key):
    forecast = _forecast_flow(acme, marker(own_key))

    with _started_by(acme_key):
        assert_run_admitted(_subject(forecast))


def test_a_purged_then_recreated_secret_name_refuses_the_plugin_s_run(acme, acme_key, own_key, redis_client_mock):
    forecast = _forecast_flow(acme, marker(own_key))
    _purge_and_recreate(own_key)
    redis_client_mock.reset_mock()

    response = service_account_client(acme_key, acme).post(
        reverse("run-session"), {"graph_id": forecast.pk, "variables": {}}, format="json"
    )

    assert response.status_code == 409, response.content
    assert response.json() == REFUSAL
    assert KEY_NAME not in response.content.decode()
    assert not Session.objects.exists()
    redis_client_mock.publish.assert_not_called()


def test_a_person_running_the_same_flow_is_not_refused(acme, own_key):
    forecast = _forecast_flow(acme, marker(own_key))
    _purge_and_recreate(own_key)

    assert_run_admitted(_subject(forecast))


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Key": "epicstaff_secret(NO_SUCH_KEY)"},
        {"X-Key": f"epicstaff_secret({KEY_NAME})", "X-Other": "epicstaff_secret(ACME_KEY)"},
    ],
    ids=["a_name_no_secret_has", "one_of_two_names_is_a_person_s"],
)
def test_a_marker_naming_anything_but_the_plugin_s_own_secret_refuses_its_run(acme, acme_key, own_key, headers):
    secret_row(acme, "ACME_KEY")
    forecast = _forecast_flow(acme, headers)

    with _started_by(acme_key), pytest.raises(SecretMarkerNotReferenceableError):
        assert_run_admitted(_subject(forecast))


def test_a_rebinding_while_the_run_is_built_refuses_it_before_the_handover(acme, acme_key, own_key):
    forecast = _forecast_flow(acme, marker(own_key))

    with _started_by(acme_key) as scope:
        admission = assert_run_admitted(_subject(forecast))
        # Meanwhile, in a person's request: a secret saved under the plugin's principal would be
        # recorded as the plugin's.
        principal, scope.principal = scope.principal, None
        _purge_and_recreate(own_key)
        scope.principal = principal
        with pytest.raises(SecretMarkerNotReferenceableError):
            assert_still_admitted(admission)


def _flow_with_configs(acme, grant, configs: int):
    """A flow whose decision table asks `configs` LLM configs, each with a marker of its own key."""
    graph = flow(acme, f"Forecast {configs}")
    node = ClassificationDecisionTableNode.objects.create(graph=graph, node_name="cdt")
    for number in range(configs):
        secret = secret_row(acme, f"Gateway key {configs}-{number}")
        own(secret, grant)
        config = llm_config(acme, f"Classifier {configs}-{number}", extra_headers=marker(secret))
        ClassificationDecisionTablePrompt.objects.create(cdt_node=node, prompt_key=f"p{number}", llm_config=config)
    return graph


def _queries_of_a_plugin_check(acme_key, graph) -> int:
    with _started_by(acme_key), CaptureQueriesContext(connection) as captured:
        PluginRunGuard().check(_subject(graph))
    return len(captured.captured_queries)


def test_the_guard_s_queries_do_not_grow_with_the_markers_a_plugin_s_run_resolves(acme, acme_key, grant):
    one, six = _flow_with_configs(acme, grant, 1), _flow_with_configs(acme, grant, 6)
    # Look-ups a running server has cached long ago.
    _queries_of_a_plugin_check(acme_key, one)

    assert _queries_of_a_plugin_check(acme_key, one) == _queries_of_a_plugin_check(acme_key, six)


# ---- indexing ----


@pytest.fixture
def knowledge_client(monkeypatch):
    """The HTTP client to knowledge_new, recording what the view sends."""
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr("tables.views.views.KnowledgeClient", lambda: client)
    return client


def _naive_rag(acme, headers) -> NaiveRag:
    collection = SourceCollection.objects.create(collection_name="Forecasts", org=acme)
    DocumentMetadata.objects.create(source_collection=collection, file_name="a.txt")
    embedder = EmbeddingConfig.objects.create(custom_name="Weather embeddings", org=acme, extra_headers=headers)
    return NaiveRag.objects.create(
        base_rag_type=BaseRagType.objects.create(source_collection=collection, rag_type=BaseRagType.RagType.NAIVE),
        embedder=embedder,
    )


def _index(acme, acme_key, rag):
    return service_account_client(acme_key, acme).post(
        "/api/process-rag-indexing/",
        {"rag_id": rag.naive_rag_id, "rag_type": "naive", "document_config_ids": [1]},
        format="json",
    )


def test_a_plugin_indexes_with_a_header_marker_of_its_own_secret(acme, acme_key, own_key, knowledge_client):
    response = _index(acme, acme_key, _naive_rag(acme, marker(own_key)))

    assert response.status_code == 202, response.content
    assert knowledge_client.index.call_args.kwargs["embedding_extra_headers"] == {"Authorization": "Bearer sk-weather"}


def test_a_purged_then_recreated_secret_name_refuses_the_plugin_s_indexing(acme, acme_key, own_key, knowledge_client):
    rag = _naive_rag(acme, marker(own_key))
    _purge_and_recreate(own_key)

    response = _index(acme, acme_key, rag)

    assert response.status_code == 409, response.content
    assert response.json() == REFUSAL
    knowledge_client.index.assert_not_called()
