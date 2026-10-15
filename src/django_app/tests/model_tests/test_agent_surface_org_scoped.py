import pytest
from django.db import IntegrityError, transaction

from agents.models import AgentDefinition
from agents.models.surface_models import Surface
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

UNIQUE_NAME_CONSTRAINTS = {
    AgentDefinition: "unique_agent_definition_name_per_organization",
    Surface: "uniq_surface_org_name",
}


@pytest.mark.django_db
@pytest.mark.parametrize("model", list(UNIQUE_NAME_CONSTRAINTS))
def test_a_name_is_unique_within_an_org_but_free_across_orgs(model, acme, beta):
    model.objects.create(org=acme, name="shared-name")
    model.objects.create(org=beta, name="shared-name")

    with pytest.raises(IntegrityError, match=UNIQUE_NAME_CONSTRAINTS[model]), transaction.atomic():
        model.objects.create(org=acme, name="shared-name")


@pytest.mark.django_db
@pytest.mark.parametrize("model", list(UNIQUE_NAME_CONSTRAINTS))
def test_a_row_without_an_org_is_rejected_by_the_database(model):
    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(name="orgless")
