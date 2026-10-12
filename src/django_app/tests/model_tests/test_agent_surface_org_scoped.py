import pytest
from django.db import IntegrityError, connection, transaction

from agents.models import AgentDefinition
from agents.models.surface_models import Surface
from rbac.authorship.registry import author_tracked_models
from rbac.models.org_scoped import OrgScopedModel
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ORG_OWNED_MODELS = [AgentDefinition, Surface]
UNIQUE_NAME_CONSTRAINTS = {
    AgentDefinition: "unique_agent_definition_name_per_organization",
    Surface: "uniq_surface_org_name",
}


def _column_is_nullable(table: str, column: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s",
            [table, column],
        )
        return cursor.fetchone()[0]


@pytest.mark.parametrize("model", ORG_OWNED_MODELS)
def test_model_inherits_org_scoped_model(model):
    assert issubclass(model, OrgScopedModel)


@pytest.mark.parametrize("model", ORG_OWNED_MODELS)
def test_model_has_no_organization_field(model):
    field_names = {field.name for field in model._meta.get_fields()}

    assert "organization" not in field_names
    assert {"org", "created_by"} <= field_names


@pytest.mark.django_db
@pytest.mark.parametrize("model", ORG_OWNED_MODELS)
def test_org_column_is_not_null_in_database(model):
    assert _column_is_nullable(model._meta.db_table, "org_id") == "NO"
    assert _column_is_nullable(model._meta.db_table, "created_by_id") == "YES"


@pytest.mark.django_db
@pytest.mark.parametrize("model", ORG_OWNED_MODELS)
def test_org_index_exists_in_database(model):
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, model._meta.db_table)
    declared_index_names = {
        index.name for index in model._meta.indexes if index.fields == ["org"]
    }

    assert declared_index_names
    assert declared_index_names <= set(constraints)


@pytest.mark.django_db
@pytest.mark.parametrize("model", ORG_OWNED_MODELS)
def test_name_is_unique_per_org_under_the_kept_constraint_name(model, acme, beta):
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, model._meta.db_table)
    constraint_name = UNIQUE_NAME_CONSTRAINTS[model]
    model.objects.create(org=acme, name="shared-name")
    model.objects.create(org=beta, name="shared-name")

    assert constraints[constraint_name]["columns"] == ["org_id", "name"]
    with pytest.raises(IntegrityError, match=constraint_name), transaction.atomic():
        model.objects.create(org=acme, name="shared-name")


@pytest.mark.django_db
@pytest.mark.parametrize("model", ORG_OWNED_MODELS)
def test_row_without_org_is_rejected_by_database(model):
    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(name="orgless")


@pytest.mark.parametrize("model", ORG_OWNED_MODELS)
def test_model_is_author_tracked_through_org_id(model):
    assert dict(author_tracked_models())[model] == "org_id"
