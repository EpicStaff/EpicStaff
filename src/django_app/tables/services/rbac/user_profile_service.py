from typing import Optional, Tuple

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Prefetch
from loguru import logger

from tables.models.rbac_models import Organization, OrganizationUser
from tables.services.rbac.auth_service import TokenPair
from tables.services.rbac.permission_resolver import PermissionResolver
from tables.services.rbac.rbac_exceptions import (
    InvalidCurrentPasswordError,
    InvalidPasswordChangeTicketError,
    OrgMembershipRequiredError,
)
from tables.services.rbac.utils.password_change_ticket_service import (
    PasswordChangeTicketService,
)
from tables.services.rbac.utils.password_writer import PasswordWriter
from tables.services.rbac.utils.session_invalidation_service import (
    SessionInvalidationService,
)
from tables.services.rbac.utils.user_avatar_storage_service import (
    UserAvatarStorageService,
)


class UserProfileService:
    """Single orchestrator for /api/profile/* endpoints.

    Composes single-purpose collaborators via constructor DI so each
    seam (avatar storage, ticket service, password writer, session
    invalidator) is swappable in tests.
    """

    def __init__(
        self,
        avatar_storage: Optional[UserAvatarStorageService] = None,
        password_change_ticket: Optional[PasswordChangeTicketService] = None,
        password_writer: Optional[PasswordWriter] = None,
        session_invalidator: Optional[SessionInvalidationService] = None,
        permission_resolver: Optional[PermissionResolver] = None,
    ):
        self._avatar_storage = avatar_storage or UserAvatarStorageService()
        self._password_change_ticket = (
            password_change_ticket or PasswordChangeTicketService()
        )
        self._password_writer = password_writer or PasswordWriter()
        self._session_invalidator = session_invalidator or SessionInvalidationService()
        self._permission_resolver = permission_resolver or PermissionResolver()

    # ---- read ----

    def get_profile(self, user, active_org_id: Optional[int] = None):
        """Refetch the user with memberships prefetched (active orgs only).
        If `active_org_id` is provided AND the caller has membership (or is
        superadmin), attach `_active_organization_id` and `_active_permissions`
        to the returned User instance for the serializer to render. Soft-fail:
        invalid `active_org_id` results in both attributes being None (NOT 403).
        """
        User = get_user_model()
        user = (
            User.objects.filter(pk=user.pk)
            .prefetch_related(
                Prefetch(
                    "organization_memberships",
                    queryset=OrganizationUser.objects.filter(org__is_active=True)
                    .select_related("org", "role")
                    .order_by("joined_at"),
                )
            )
            .get()
        )

        user._active_organization_id = None
        user._active_permissions = None
        if active_org_id is not None:
            # Confirm the org exists; missing orgs soft-fail (returns nulls).
            if not Organization.objects.filter(pk=active_org_id).exists():
                return user
            try:
                effective = self._permission_resolver.resolve(
                    user=user, org_id=active_org_id
                )
            except OrgMembershipRequiredError:
                return user
            user._active_organization_id = active_org_id
            user._active_permissions = {
                "is_superadmin": effective.is_superadmin,
                "role": (
                    None
                    if effective.role is None
                    else {"id": effective.role.id, "name": effective.role.name}
                ),
                "permissions": effective.to_action_codes(),
            }
        return user

    # ---- profile field updates ----

    def update_display_name(self, user, display_name: Optional[str]):
        """Set or clear display_name. None clears (column allows NULL)."""
        user.display_name = display_name
        user.save(update_fields=["display_name", "updated_at"])
        logger.info(
            "profile.display_name_updated user_id={} cleared={}",
            user.id,
            display_name is None,
        )
        return user

    # ---- avatar ----

    def update_avatar(self, user, uploaded_file):
        """Validate and store the avatar; previous file deleted on
        commit via UserAvatarStorageService.store."""
        result = self._avatar_storage.store(user, uploaded_file)
        logger.info("profile.avatar_updated user_id={}", user.id)
        return result

    def clear_avatar(self, user):
        """Clear avatar pointer; previous file deleted on commit."""
        result = self._avatar_storage.clear(user)
        logger.info("profile.avatar_cleared user_id={}", user.id)
        return result

    # ---- password change (two-step) ----

    def password_change_request(self, user, current_password: str) -> Tuple[str, int]:
        """Verify current_password and issue a single-use ticket.

        Raises InvalidCurrentPasswordError on mismatch. Returns
        (ticket, expires_in).
        """
        if not user.check_password(current_password):
            logger.info("profile.password_change_request_failed user_id={}", user.id)
            raise InvalidCurrentPasswordError()
        ticket, expires_in = self._password_change_ticket.issue(user)
        logger.info("profile.password_change_request_issued user_id={}", user.id)
        return ticket, expires_in

    def password_change_confirm(
        self, actor, ticket: str, new_password: str
    ) -> TokenPair:
        """Step 2: consume ticket, write new password, blacklist all
        outstanding refresh tokens, mint a fresh pair.

        Dual binding: ticket must exist AND must belong to the calling
        actor. Mismatch surfaces as the same generic
        InvalidPasswordChangeTicketError so a third party cannot probe
        whether a ticket exists for another user.
        """
        target = self._password_change_ticket.consume(ticket)
        if target is None or actor is None or target.id != actor.id:
            logger.info(
                "profile.password_change_confirm_rejected actor_id={}",
                getattr(actor, "id", None),
            )
            raise InvalidPasswordChangeTicketError()
        with transaction.atomic():
            self._password_writer.set(target, new_password)
        self._session_invalidator.blacklist_all_for_user(target)
        logger.info("profile.password_change_confirmed user_id={}", target.id)
        return TokenPair.for_user(target)
