import pytest
from django.utils import timezone

from tables.models import Graph
from tables.services.copy_services.helpers import next_copy_name
from tests.rbac_cross_org_fixtures import acme, beta  # noqa: F401


@pytest.mark.django_db
def test_next_copy_name_skips_names_taken_in_same_org(acme):
    Graph.objects.create(name="Flow", org=acme)
    Graph.objects.create(name="Flow #2", org=acme)

    assert next_copy_name(Graph, org_id=acme.id, base_name="Flow") == "Flow #3"


@pytest.mark.django_db
def test_next_copy_name_ignores_names_in_other_org(acme, beta):
    Graph.objects.create(name="Flow", org=beta)
    Graph.objects.create(name="Flow #2", org=beta)

    assert next_copy_name(Graph, org_id=acme.id, base_name="Flow") == "Flow"


@pytest.mark.django_db
def test_next_copy_name_ignores_soft_deleted_rows(acme):
    Graph.objects.create(
        name="Flow", org=acme, is_soft_deleted=True, soft_deleted_at=timezone.now()
    )

    assert next_copy_name(Graph, org_id=acme.id, base_name="Flow") == "Flow"
