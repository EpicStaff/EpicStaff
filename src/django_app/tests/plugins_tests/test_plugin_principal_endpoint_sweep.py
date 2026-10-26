"""A sweep of EpicStaff's API with a real service-account key that may do everything a plugin may.

The principal is not a `User`: any endpoint that reads a user attribute off it (an id for an
author, a favorite, an editor, a throttle) would answer 500. Every list and create must
answer 2xx or 4xx instead, and the main write paths must succeed. Runs with committed
transactions, so the `on_commit` work of each write runs too.
"""

import re

import pytest
from django.urls import reverse
from plugins.access.declared_access import NON_DECLARABLE_RESOURCE_TYPES
from rbac.access.bitmask import bitmask_to_actions
from rbac.access.catalog import RESOURCE_TYPE_METADATA, applicable_actions_for, grantable_bits_for
from tables.graph_collab.notifications import GraphEditNotifier
from tables.models import Graph

from tests.plugins_tests.conftest import service_account_client
from tests.plugins_tests.service_account_helpers import runnable_graph
from tests.plugins_tests.view_walker import drf_views

pytestmark = [pytest.mark.django_db(transaction=True)]

# A plain list route of the router: `api/^graphs/$`.
_LIST_ROUTE = re.compile(r"^api/\^(?P<path>[a-z0-9-]+/)\$$")


def _everything_a_plugin_may_declare():
    return [
        {
            "resource_type": entry["code"],
            "actions": bitmask_to_actions(grantable_bits_for(entry["code"]), applicable_actions_for(entry["code"])),
            "reason": "Sweep.",
        }
        for entry in RESOURCE_TYPE_METADATA
        if entry["code"] not in NON_DECLARABLE_RESOURCE_TYPES and grantable_bits_for(entry["code"])
    ]


def _list_routes():
    routes = set()
    for view in drf_views():
        match = _LIST_ROUTE.match(view.route)
        if match and view.dotted_path.startswith(("tables.", "agents.")):
            routes.add(f"/api/{match['path']}")
    return sorted(routes)


@pytest.fixture
def sweeper(weather_backend, service_account_key, acme):
    plugin = weather_backend(access=_everything_a_plugin_may_declare())
    return service_account_client(service_account_key(plugin, acme), acme)


def test_no_list_or_create_answers_500(sweeper):
    routes = _list_routes()
    assert "/api/graphs/" in routes and "/api/secrets/" in routes

    failures = []
    for url in routes:
        for method in ("get", "post"):
            response = getattr(sweeper, method)(url, {}, format="json")
            if response.status_code >= 500:
                failures.append(f"{method.upper()} {url} -> {response.status_code}")

    assert failures == []


def test_the_main_writes_succeed(sweeper, acme, redis_client_mock, monkeypatch):
    broadcasts = []
    monkeypatch.setattr(GraphEditNotifier, "_send", staticmethod(lambda graph_id, message: broadcasts.append(message)))
    graph = runnable_graph("Swept flow", acme)

    run = sweeper.post(reverse("run-session"), {"graph_id": graph.pk, "variables": {}}, format="json")
    patched = sweeper.patch(f"/api/graphs/{graph.pk}/", {"description": "Swept", "save_version": graph.save_version}, format="json")
    graph.refresh_from_db()
    saved = sweeper.post(reverse("graphs-save-flow", args=[graph.pk]), {"save_version": graph.save_version}, format="json")
    created = {
        url: sweeper.post(url, body, format="json").status_code
        for url, body in (
            ("/api/graphs/", {"name": "Created by the sweep"}),
            ("/api/secrets/", {"name": "SWEEP", "value": "v"}),
            ("/api/llm-configs/", {"custom_name": "Sweep"}),
            ("/api/key-value-tables/", {"name": "sweep"}),
            ("/api/labels/", {"name": "Sweep"}),
        )
    }

    assert run.status_code == 201, run.content
    assert patched.status_code == 200, patched.content
    assert saved.status_code == 200, saved.content
    assert created == dict.fromkeys(created, 201)
    assert Graph.objects.filter(name="Created by the sweep", org=acme).exists()
    assert [message["saved_by"] for message in broadcasts] == [
        {"user_id": None, "display_name": "Weather (plugin)", "avatar_url": None}
    ] * 2
