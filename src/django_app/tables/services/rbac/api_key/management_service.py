from collections import defaultdict
from datetime import datetime
from typing import Optional

from django.db.models import F, Q, QuerySet
from django.utils import timezone
from loguru import logger

from tables.models.rbac_models import ApiKey, OrganizationUser
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.rbac.cross_org_permission_resolver import OrgScope
from tables.services.rbac.cross_org_service import CrossOrgResourceService
from tables.services.rbac.rbac_exceptions import ApiKeyNotFoundError

OWNER_ORG_PATH = "created_by__organization_memberships__org_id"


class ApiKeyManagementService(CrossOrgResourceService):
    """Cross-org management of members' USER keys.

    A key owns no organization: its scope is the set its owner belongs to.
    A superadmin owner has none, so their keys are unreachable to delegates.
    """

    rbac_resource_type = ResourceType.API_KEYS
    not_found_exception = ApiKeyNotFoundError
    delegated_scope_q: Q = Q(created_by__is_superadmin=False)

    def list_keys(
        self,
        actor,
        org_ids: Optional[list[int]],
        owner_id: Optional[int] = None,
        status_value: Optional[str] = None,
        search: Optional[str] = None,
        scopes: Optional[list[OrgScope]] = None,
    ) -> QuerySet[ApiKey]:
        """USER keys owned by members of the caller's readable orgs."""
        base_qs: QuerySet[ApiKey] = ApiKey.objects.filter(
            key_type=ApiKey.KeyType.USER
        ).select_related("created_by")
        qs: QuerySet[ApiKey] = self.apply_org_scope(
            actor=actor,
            org_ids=org_ids,
            base_qs=base_qs,
            org_field=OWNER_ORG_PATH,
            scopes=scopes,
        )
        if owner_id is not None:
            qs = qs.filter(created_by_id=owner_id)
        if status_value is not None:
            qs = self._filter_status(qs, status_value)
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(prefix__icontains=search))
        # distinct(): the owner-membership join is multi-valued.
        return qs.distinct().order_by(
            F("last_used_at").desc(nulls_last=True), "-created_at", "id"
        )

    def revoke_key(
        self, actor, key_id: int, scopes: Optional[list[OrgScope]] = None
    ) -> ApiKey:
        """Disable a key everywhere, keeping the row. Idempotent."""
        key: ApiKey = self._get_key_or_404(key_id)
        self.authorize_any_org(
            actor, self._owner_org_ids(key), Permission.DELETE, scopes=scopes
        )
        if key.revoked_at is None:
            key.revoked_at = timezone.now()
            key.save(update_fields=["revoked_at"])
        logger.info(
            "ApiKeyManagementService.revoke_key actor={a} key={k} owner={o}",
            a=getattr(actor, "email", "system"),
            k=key.pk,
            o=key.created_by_id,
        )
        return key

    def delete_key(
        self, actor, key_id: int, scopes: Optional[list[OrgScope]] = None
    ) -> None:
        key: ApiKey = self._get_key_or_404(key_id)
        self.authorize_any_org(
            actor, self._owner_org_ids(key), Permission.DELETE, scopes=scopes
        )
        logger.info(
            "ApiKeyManagementService.delete_key actor={a} key={k} owner={o}",
            a=getattr(actor, "email", "system"),
            k=key.pk,
            o=key.created_by_id,
        )
        key.delete()

    def attach_visible_orgs(
        self, keys: list[ApiKey], actor, scopes: Optional[list[OrgScope]] = None
    ) -> None:
        """Set `_visible_org_ids` on each key: the owner's orgs, limited to
        those the caller may read. One query for the whole page."""
        owner_ids: set[int] = {key.created_by_id for key in keys}
        if not owner_ids:
            return
        readable: Optional[set[int]] = self.resolve_readable_org_ids(
            actor, scopes=scopes
        )
        rows: QuerySet[OrganizationUser] = OrganizationUser.objects.filter(
            user_id__in=owner_ids, org__is_active=True
        )
        if readable is not None:
            rows = rows.filter(org_id__in=readable)
        by_owner: dict[int, list[int]] = defaultdict(list)
        for user_id, org_id in rows.values_list("user_id", "org_id"):
            by_owner[user_id].append(org_id)
        for key in keys:
            key._visible_org_ids = sorted(by_owner.get(key.created_by_id, []))

    @staticmethod
    def _get_key_or_404(key_id: int) -> ApiKey:
        """Owner status is not filtered here — a superadmin caller must reach
        every key, and `authorize_any_org` bypasses before the org check."""
        key: Optional[ApiKey] = (
            ApiKey.objects.filter(pk=key_id, key_type=ApiKey.KeyType.USER)
            .select_related("created_by")
            .first()
        )
        if key is None:
            raise ApiKeyNotFoundError()
        return key

    @staticmethod
    def _owner_org_ids(key: ApiKey) -> set[int]:
        """Orgs governing a key. A superadmin owner has none."""
        if key.created_by.is_superadmin:
            return set()
        return set(
            OrganizationUser.objects.filter(
                user_id=key.created_by_id, org__is_active=True
            ).values_list("org_id", flat=True)
        )

    @staticmethod
    def _filter_status(qs: QuerySet[ApiKey], status_value: str) -> QuerySet[ApiKey]:
        now: datetime = timezone.now()
        if status_value == "revoked":
            return qs.filter(revoked_at__isnull=False)
        if status_value == "expired":
            return qs.filter(revoked_at__isnull=True, expires_at__lte=now)
        return qs.filter(revoked_at__isnull=True).exclude(expires_at__lte=now)
