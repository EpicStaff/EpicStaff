from django.db.models import F, Q
from django.utils import timezone

from tables.models.rbac_models import ApiKey
from tables.services.rbac.rbac_exceptions import ApiKeyNotFoundError

ALLOWED_STATUS_FILTERS = ("active", "expired", "revoked")


class ApiKeyAdminService:
    """Org-scoped management over USER keys.

    Scope rule: a key is manageable iff its owner is a member of `org_id`
    (the caller's active org). `org_id=None` (superadmin without header)
    lifts the org filter. SYSTEM keys never appear anywhere here.
    """

    def list_keys(self, org_id, owner_id=None, status_value=None, search=None):
        qs = (
            ApiKey.objects.filter(key_type=ApiKey.KeyType.USER)
            .select_related("created_by")
            .order_by(F("last_used_at").desc(nulls_last=True), "-created_at")
        )
        if org_id is not None:
            qs = qs.filter(created_by__organization_memberships__org_id=org_id)
        if owner_id is not None:
            qs = qs.filter(created_by_id=owner_id)
        if status_value is not None:
            qs = self._filter_status(qs, status_value)
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(prefix__icontains=search))
        return qs

    def revoke_key(self, org_id, key_id) -> ApiKey:
        key = self._get_in_scope(org_id, key_id)
        if key.revoked_at is None:
            key.revoked_at = timezone.now()
            key.save(update_fields=["revoked_at"])
        return key

    def delete_key(self, org_id, key_id) -> None:
        self._get_in_scope(org_id, key_id).delete()

    def _get_in_scope(self, org_id, key_id) -> ApiKey:
        qs = ApiKey.objects.filter(id=key_id, key_type=ApiKey.KeyType.USER)
        if org_id is not None:
            qs = qs.filter(created_by__organization_memberships__org_id=org_id)
        key = qs.select_related("created_by").first()
        if key is None:
            raise ApiKeyNotFoundError()
        return key

    @staticmethod
    def _filter_status(qs, status_value):
        now = timezone.now()
        if status_value == "revoked":
            return qs.filter(revoked_at__isnull=False)
        if status_value == "expired":
            return qs.filter(revoked_at__isnull=True, expires_at__lte=now)
        # "active"
        return qs.filter(revoked_at__isnull=True).exclude(expires_at__lte=now)
