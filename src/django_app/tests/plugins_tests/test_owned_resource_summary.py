"""How many rows of each kind a grant's plugin owns, as the SuperAdmin's dialogs show them."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from plugins.ownership.owned_resource_summary import OWNED_RESOURCE_LABELS, owned_resource_summary
from plugins.ownership.ownership_recorder import ownable_models
from tables.models import Graph, StorageFile

from tests.plugins_tests.suspension_helpers import flow, llm_config, own, secret_row

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def grant(running_plugin, grant_to, acme):
    return grant_to(running_plugin(), acme)


def test_every_ownable_model_has_a_label_and_nothing_else_does():
    assert {model._meta.label for model in ownable_models()} == set(OWNED_RESOURCE_LABELS)


def test_the_summary_counts_by_model_sorted_by_label(grant, acme, beta, grant_to, running_plugin):
    for number in range(2):
        own(flow(acme, f"Forecast {number}"), grant)
    own(secret_row(acme, "Weather · LLM key"), grant)
    own(llm_config(acme, "Weather summaries"), grant)
    own(StorageFile.objects.create(org=acme, path="weather/README.md", name="README.md", parent_path="weather/"), grant)
    almanac_grant = grant_to(running_plugin(id="almanac", name="Almanac"), acme)
    own(flow(acme, "Almanac"), almanac_grant)

    assert owned_resource_summary(grant) == [
        {"model": "tables.StorageFile", "label": "Files", "count": 1},
        {"model": "tables.Graph", "label": "Flows", "count": 2},
        {"model": "tables.LLMConfig", "label": "LLM configs", "count": 1},
        {"model": "tables.Secret", "label": "Secrets", "count": 1},
    ]


def test_a_binned_resource_still_counts_and_a_deleted_one_does_not(grant, acme):
    binned = flow(acme, "Binned")
    deleted = flow(acme, "Deleted")
    for graph in (binned, deleted):
        own(graph, grant)
    binned.delete()
    Graph.all_objects.filter(pk=deleted.pk).delete()

    assert owned_resource_summary(grant) == [{"model": "tables.Graph", "label": "Flows", "count": 1}]


def test_the_summary_is_one_query_for_the_kinds_present_and_one_per_kind(grant, acme):
    own(flow(acme, "Forecast"), grant)
    own(flow(acme, "Alerts"), grant)
    own(secret_row(acme, "Weather · LLM key"), grant)
    owned_resource_summary(grant)

    with CaptureQueriesContext(connection) as captured:
        owned_resource_summary(grant)

    assert len(captured.captured_queries) == 3


def test_each_kind_is_counted_with_only_its_own_existence_check(grant, acme):
    own(flow(acme, "Forecast"), grant)
    own(secret_row(acme, "Weather · LLM key"), grant)
    owned_resource_summary(grant)

    with CaptureQueriesContext(connection) as captured:
        owned_resource_summary(grant)

    per_kind = [query["sql"] for query in captured.captured_queries[1:]]
    assert [sql.count("EXISTS") for sql in per_kind] == [1, 1]
