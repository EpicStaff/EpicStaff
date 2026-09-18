import pytest

from tables.migrations._helpers import assign_default_org
from tables.models import LLMModel, Provider
from tables.models.rbac_models import Organization


class _Apps:
    """Minimal historical-`apps` stand-in: the helper only calls get_model."""

    def get_model(self, app_label, model_name=None):
        label = app_label if model_name is None else f"{app_label}.{model_name}"
        return {"tables.LLMModel": LLMModel}[label]


@pytest.mark.django_db
def test_extra_filter_backfills_only_matching_rows():
    org = Organization.objects.create(name="Default Organization")
    provider = Provider.objects.create(name="prov-x")
    custom = LLMModel.objects.create(
        name="custom-1", llm_provider=provider, is_custom=True
    )
    builtin = LLMModel.objects.create(
        name="builtin-1", llm_provider=provider, is_custom=False
    )

    assign_default_org(
        _Apps(), "tables.LLMModel", org, extra_filter={"is_custom": True}
    )

    custom.refresh_from_db()
    builtin.refresh_from_db()
    assert custom.org_id == org.id  # custom row stamped
    assert builtin.org_id is None  # built-in left global


@pytest.mark.django_db
def test_no_extra_filter_backfills_all_null_rows():
    org = Organization.objects.create(name="Default Organization")
    provider = Provider.objects.create(name="prov-y")
    a = LLMModel.objects.create(name="a", llm_provider=provider, is_custom=True)
    b = LLMModel.objects.create(name="b", llm_provider=provider, is_custom=False)

    assign_default_org(_Apps(), "tables.LLMModel", org)

    a.refresh_from_db()
    b.refresh_from_db()
    assert a.org_id == org.id and b.org_id == org.id
