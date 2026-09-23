import pytest

from tables.models.graph_models import Graph
from tables.models.rbac_models import Organization
from tables.services.rbac.delete_collector import build_collector, summarize


@pytest.fixture
def org_with_graphs(db):
    org = Organization.objects.create(name="Cascade Test Org")
    for index in range(3):
        Graph.objects.create(name=f"graph-{index}", org=org)
    return org


@pytest.mark.django_db
def test_report_counts_the_root_instance(org_with_graphs):
    report = summarize(build_collector(org_with_graphs))
    rows = {row.model: row.count for row in report}
    assert rows["tables.Organization"] == 1


@pytest.mark.django_db
def test_report_counts_cascaded_children(org_with_graphs):
    report = summarize(build_collector(org_with_graphs))
    rows = {row.model: row.count for row in report}
    assert rows["tables.Graph"] == 3


@pytest.mark.django_db
def test_by_model_is_sorted_by_descending_count(org_with_graphs):
    report = summarize(build_collector(org_with_graphs))
    counts = [row.count for row in report]
    assert counts == sorted(counts, reverse=True)


@pytest.mark.django_db
def test_zero_count_models_are_omitted(org_with_graphs):
    report = summarize(build_collector(org_with_graphs))
    assert all(row.count > 0 for row in report)


@pytest.mark.django_db
def test_report_does_not_delete_anything(org_with_graphs):
    summarize(build_collector(org_with_graphs))
    assert Organization.objects.filter(pk=org_with_graphs.pk).exists()
    assert Graph.objects.filter(org=org_with_graphs).count() == 3
