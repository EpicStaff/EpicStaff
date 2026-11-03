from datetime import datetime

from django.db.models import F, Q, QuerySet
from django.utils import timezone
from loguru import logger

from rbac.access.cross_org_resolver import OrgScope
from rbac.exceptions import ApiKeyNotFoundError
from rbac.governance.cross_org_base import CrossOrgResourceService
from rbac.models import ApiKey
from rbac.models.enums import Permission, ResourceType


class ApiKeyManagementService(CrossOrgResourceService):
    """Cross-org management of members' USER keys.

    A key belongs to one org (`ApiKey.org`) and is governed only there: the
    caller needs api_keys rights in the key's org, whatever other orgs the
    owner belongs to. Superadmin-owned keys are reachable only by superadmins.
    """

    rbac_resource_type = ResourceType.API_KEYS
    not_found_exception = ApiKeyNotFoundError
    delegated_scope_q: Q = Q(created_by__is_superadmin=False)

    def list_keys(
        self,
        actor,
        org_ids: list[int] | None,
        owner_id: int | None = None,
        status_value: str | None = None,
        search: str | None = None,
        scopes: list[OrgScope] | None = None,
    ) -> QuerySet[ApiKey]:
        """USER keys of the orgs where the caller may read api_keys."""
        base_qs: QuerySet[ApiKey] = ApiKey.objects.filter(
            key_type=ApiKey.KeyType.USER
        ).select_related("created_by", "org")
        qs: QuerySet[ApiKey] = self.apply_org_scope(
            actor=actor,
            org_ids=org_ids,
            base_qs=base_qs,
            org_field="org_id",
            scopes=scopes,
        )
        if owner_id is not None:
            qs = qs.filter(created_by_id=owner_id)
        if status_value is not None:
            qs = self._filter_status(qs, status_value)
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(prefix__icontains=search))
        return qs.order_by(F("last_used_at").desc(nulls_last=True), "-created_at", "id")

    def revoke_key(self, actor, key_id: int) -> ApiKey:
        """Disable a key, keeping the row. Idempotent.

        Raises:
            ApiKeyNotFoundError: No USER key with this id the caller may see in its org.
        """
        key: ApiKey = self._get_key_for_delete(actor, key_id)
        if key.revoked_at is None:
            key.revoked_at = timezone.now()
            key.save(update_fields=["revoked_at"])
        logger.info(
            "ApiKeyManagementService.revoke_key actor={a} key={k} owner={o} org={org}",
            a=getattr(actor, "email", "system"),
            k=key.pk,
            o=key.created_by_id,
            org=key.org_id,
        )
        return key

    def delete_key(self, actor, key_id: int) -> None:
        """Remove a key's row.

        Raises:
            ApiKeyNotFoundError: No USER key with this id the caller may see in its org.
        """
        key: ApiKey = self._get_key_for_delete(actor, key_id)
        logger.info(
            "ApiKeyManagementService.delete_key actor={a} key={k} owner={o} org={org}",
            a=getattr(actor, "email", "system"),
            k=key.pk,
            o=key.created_by_id,
            org=key.org_id,
        )
        key.delete()

    def _get_key_for_delete(self, actor, key_id: int) -> ApiKey:
        """404 for a key outside the caller's reach, 403 for a visible key
        the caller may not delete."""
        qs: QuerySet[ApiKey] = ApiKey.objects.filter(
            pk=key_id, key_type=ApiKey.KeyType.USER
        ).select_related("created_by", "org")
        # `resolve_for_write` lets an org admin through on a superadmin's key in
        # their org; the list hides those keys, so this lookup must too.
        if not getattr(actor, "is_superadmin", False):
            qs = qs.filter(self.delegated_scope_q)
        key: ApiKey | None = qs.first()
        if key is None:
            raise ApiKeyNotFoundError()
        effective = self.resolve_for_write(actor, key.org_id, Permission.DELETE)
        self.assert_can(effective, Permission.DELETE)
        return key

    @staticmethod
    def _filter_status(qs: QuerySet[ApiKey], status_value: str) -> QuerySet[ApiKey]:
        now: datetime = timezone.now()
        if status_value == "revoked":
            return qs.filter(revoked_at__isnull=False)
        if status_value == "expired":
            return qs.filter(revoked_at__isnull=True, expires_at__lte=now)
        return qs.filter(revoked_at__isnull=True).exclude(expires_at__lte=now)
