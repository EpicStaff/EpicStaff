import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models import ResourceLastEdit
from tables.models import Provider
from tables.services.quickstart_service import QuickstartService
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _last_edit_of(instance) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    ).first()


@pytest.fixture
def openai_provider(db) -> Provider:
    return Provider.objects.create(name="openai")


@pytest.mark.django_db
def test_quickstart_records_acting_user_on_created_configs(openai_provider, acme, admin_acme):
    started_at = timezone.now()

    result = QuickstartService().quickstart(
        provider="openai", api_key="sk-test", org_id=acme.id, user=admin_acme
    )

    assert result["success"], result
    for config in (result["llm_config"], result["embedding_config"]):
        last_edit = _last_edit_of(config)
        assert last_edit.edited_by_id == admin_acme.id
        assert last_edit.edited_at >= started_at


@pytest.mark.django_db
def test_quickstart_by_system_principal_records_time_without_editor(openai_provider, acme):
    result = QuickstartService().quickstart(
        provider="openai", api_key="sk-test", org_id=acme.id, user=SystemServicePrincipal()
    )

    assert result["success"], result
    for config in (result["llm_config"], result["embedding_config"]):
        last_edit = _last_edit_of(config)
        assert last_edit.edited_by_id is None
        assert last_edit.edited_at is not None
