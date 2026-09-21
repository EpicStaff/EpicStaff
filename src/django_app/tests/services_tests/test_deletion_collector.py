import pytest

from tables.models.graph_models import Graph
from tables.models.rbac_models import Organization
from tables.services.rbac.delete.collector import collect_deletion_report


@pytest.fixture
def org_with_graphs(db):
    org = Organization.objects.create(name="Cascade Test Org")
    for index in range(3):
        Graph.objects.create(name=f"graph-{index}", org=org)
    return org


@pytest.mark.django_db
def test_report_counts_the_root_instance(org_with_graphs):
    report = collect_deletion_report(org_with_graphs)
    rows = {row["model"]: row["count"] for row in report["by_model"]}
    assert rows["tables.Organization"] == 1


@pytest.mark.django_db
def test_report_counts_cascaded_children(org_with_graphs):
    report = collect_deletion_report(org_with_graphs)
    rows = {row["model"]: row["count"] for row in report["by_model"]}
    assert rows["tables.Graph"] == 3


@pytest.mark.django_db
def test_total_is_the_sum_of_by_model_counts(org_with_graphs):
    report = collect_deletion_report(org_with_graphs)
    assert report["total"] == sum(row["count"] for row in report["by_model"])


@pytest.mark.django_db
def test_by_model_is_sorted_by_descending_count(org_with_graphs):
    report = collect_deletion_report(org_with_graphs)
    counts = [row["count"] for row in report["by_model"]]
    assert counts == sorted(counts, reverse=True)


@pytest.mark.django_db
def test_zero_count_models_are_omitted(org_with_graphs):
    report = collect_deletion_report(org_with_graphs)
    assert all(row["count"] > 0 for row in report["by_model"])


@pytest.mark.django_db
def test_field_updates_report_set_null_fixups(db, django_user_model):
    """A user's created_by references are SET_NULL, not deleted."""
    user = django_user_model.objects.create_user(
        email="author@x.com", password="StrongPass123!"
    )
    org = Organization.objects.create(name="Author Org")
    Graph.objects.create(name="authored", org=org, created_by=user)

    report = collect_deletion_report(user)
    updates = {(row["model"], row["field"]): row for row in report["field_updates"]}
    assert updates[("tables.Graph", "created_by")]["action"] == "SET_NULL"
    assert updates[("tables.Graph", "created_by")]["count"] == 1


@pytest.mark.django_db
def test_report_does_not_delete_anything(org_with_graphs):
    collect_deletion_report(org_with_graphs)
    assert Organization.objects.filter(pk=org_with_graphs.pk).exists()
    assert Graph.objects.filter(org=org_with_graphs).count() == 3


@pytest.mark.django_db
def test_field_updates_omit_rows_the_same_delete_removes(db):
    """A SET_NULL edge whose holder the cascade also destroys is reported as removed, never as nulled."""
    from tables.models.session_models import Session

    org = Organization.objects.create(name="Session Org")
    graph = Graph.objects.create(name="session-graph", org=org)
    parent = Session.objects.create(graph=graph, status=Session.SessionStatus.END)
    Session.objects.create(
        graph=graph, status=Session.SessionStatus.END, parent_session=parent
    )

    report = collect_deletion_report(org)

    rows = {row["model"]: row["count"] for row in report["by_model"]}
    assert rows["tables.Session"] == 2
    assert not [
        row for row in report["field_updates"] if row["model"] == "tables.Session"
    ], "a row the delete removes must not also be reported as nulled"
