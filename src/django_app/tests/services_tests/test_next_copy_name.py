import pytest
from django.db.models import Q
from django.utils import timezone

from tables.models import Graph
from tables.models.python_models import PythonCode, PythonCodeTool
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


def _make_built_in_python_code_tool(name: str) -> PythonCodeTool:
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(
        name=name, description="desc", python_code=code, built_in=True, org=None
    )


@pytest.mark.django_db
def test_next_copy_name_treats_also_taken_rows_as_taken(acme):
    _make_built_in_python_code_tool("Foo")

    assert (
        next_copy_name(
            PythonCodeTool, org_id=acme.id, base_name="Foo", also_taken=Q(built_in=True)
        )
        == "Foo #2"
    )


@pytest.mark.django_db
def test_next_copy_name_without_also_taken_ignores_built_in_rows(acme):
    _make_built_in_python_code_tool("Foo")

    assert next_copy_name(PythonCodeTool, org_id=acme.id, base_name="Foo") == "Foo"


@pytest.mark.django_db
def test_next_copy_name_also_taken_does_not_widen_to_other_org(acme, beta):
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    PythonCodeTool.objects.create(
        name="Foo", description="desc", python_code=code, built_in=False, org=beta
    )

    assert (
        next_copy_name(
            PythonCodeTool, org_id=acme.id, base_name="Foo", also_taken=Q(built_in=True)
        )
        == "Foo"
    )
