import pytest

from rbac.serializers.organizations import (
    AUDIT_RETENTION_DAYS_MAX,
    OrganizationSettingsUpdateSerializer,
)


@pytest.mark.parametrize("days", [0, 30, AUDIT_RETENTION_DAYS_MAX])
def test_accepts_retention_within_storable_range(days):
    serializer = OrganizationSettingsUpdateSerializer(
        data={"audit_retention_days": days}
    )

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["audit_retention_days"] == days


@pytest.mark.parametrize("days", [-1, AUDIT_RETENTION_DAYS_MAX + 1, 10**20])
def test_rejects_retention_outside_storable_range_as_validation_error(days):
    serializer = OrganizationSettingsUpdateSerializer(
        data={"audit_retention_days": days}
    )

    assert not serializer.is_valid()
    assert "audit_retention_days" in serializer.errors
