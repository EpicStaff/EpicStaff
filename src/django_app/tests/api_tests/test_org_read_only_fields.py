import pytest

from tables.models.rbac_models import Organization
from tables.serializers.model_serializers.llm_serializers import LLMConfigSerializer


@pytest.mark.django_db
class TestOrgManagedFieldsReadOnly:
    """`org`/`created_by` are server-managed and must be ignored as client input.

    Regression for the 500 IntegrityError on PUT/PATCH /api/llm-configs/<id>/
    where a client-supplied `org: null` nulled the NOT NULL org column.
    """

    def test_update_ignores_client_org_null(self, llm_config):
        original_org_id = llm_config.org_id
        assert original_org_id is not None

        serializer = LLMConfigSerializer(
            instance=llm_config, data={"org": None}, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        llm_config.refresh_from_db()
        assert llm_config.org_id == original_org_id

    def test_update_ignores_client_org_move(self, llm_config, default_org):
        other_org = Organization.objects.create(name="Other Org")

        serializer = LLMConfigSerializer(
            instance=llm_config, data={"org": other_org.id}, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        llm_config.refresh_from_db()
        assert llm_config.org_id == default_org.id
