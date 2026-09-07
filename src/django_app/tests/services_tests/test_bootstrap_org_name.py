import pytest
from django.test import override_settings

from tables.models.rbac_models import Organization
from tables.services.rbac.first_setup_service import FirstSetupService


@pytest.mark.django_db
def test_org_name_names_a_newly_created_organization():
    result = FirstSetupService().setup(
        email="admin@example.com", password="StrongPass123!", org_name="Acme Inc"
    )
    assert result.organization.name == "Acme Inc"
    assert result.default_org_created is True
    assert Organization.objects.get(is_default=True).name == "Acme Inc"


@pytest.mark.django_db
def test_org_name_is_ignored_when_a_default_org_already_exists():
    """The is_default flag is the rename-proof anchor other code depends on;
    a bootstrap command must never rename an existing organization."""
    existing = Organization.objects.create(name="Renamed By Operator", is_default=True)

    result = FirstSetupService().setup(
        email="admin@example.com", password="StrongPass123!", org_name="Acme Inc"
    )

    existing.refresh_from_db()
    assert existing.name == "Renamed By Operator"
    assert result.organization.pk == existing.pk
    assert result.default_org_created is False


@pytest.mark.django_db
@override_settings(DEFAULT_ORGANIZATION_NAME="Configured Co")
def test_org_name_defaults_to_settings_when_omitted():
    """Pinned with override_settings: DEFAULT_ORGANIZATION_NAME is read from
    the environment, so asserting a bare default would fail on any machine
    that exports it."""
    result = FirstSetupService().setup(
        email="admin@example.com", password="StrongPass123!"
    )
    assert result.organization.name == "Configured Co"


@pytest.mark.django_db
@override_settings(DEFAULT_ORGANIZATION_NAME="")
def test_blank_settings_org_name_falls_back_at_point_of_use():
    """docker-compose forwards DEFAULT_ORGANIZATION_NAME unconditionally, so
    an operator with no value in .env used to get an organization named ""."""
    result = FirstSetupService().setup(
        email="admin@example.com", password="StrongPass123!"
    )
    assert result.organization.name == "Organization"
