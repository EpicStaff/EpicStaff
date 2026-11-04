from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.functions import Lower
from django.utils import timezone
from loguru import logger
from tables.models.user import TOURS_MAX_PER_USER, UserTourProgress

from rbac.access.resolver import PermissionResolver
from rbac.exceptions import (
    InvalidCurrentPasswordError,
    InvalidPasswordChangeTicketError,
    OrgMembershipRequiredError,
    TourLimitExceededError,
)
from rbac.identity.credential_revocation import (
    CredentialRevocationService,
)
from rbac.identity.passwords.change_ticket import (
    PasswordChangeTicketService,
)
from rbac.identity.passwords.writer import PasswordWriter
from rbac.identity.tokens import TokenPair
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from rbac.profile.avatar import (
    UserAvatarStorageService,
)


class UserProfileService:
    """Single orchestrator for /api/profile/* endpoints.

    Composes single-purpose collaborators via constructor DI so each
    seam (avatar storage, ticket service, password writer, credential
    revoker) is swappable in tests.
    """

    def __init__(
        self,
        avatar_storage: UserAvatarStorageService | None = None,
        password_change_ticket: PasswordChangeTicketService | None = None,
        password_writer: PasswordWriter | None = None,
        credential_revoker: CredentialRevocationService | None = None,
        permission_resolver: PermissionResolver | None = None,
    ):
        self._avatar_storage = avatar_storage or UserAvatarStorageService()
        self._password_change_ticket = password_change_ticket or PasswordChangeTicketService()
        self._password_writer = password_writer or PasswordWriter()
        self._credential_revoker = credential_revoker or CredentialRevocationService()
        self._permission_resolver = permission_resolver or PermissionResolver()

    # ---- read ----

    def get_profile(
        self, user, active_org_id: int | None = None, api_key_org_id: int | None = None
    ):
        """Refetch the user and attach the memberships list and completed tours.

        `_profile_memberships` is the caller's own active memberships, or —
        for a superadmin — every active organization with the built-in
        Superadmin role. With `api_key_org_id` (the org of the caller's USER
        API key, which acts only there) it holds that org alone.
        `_completed_tours` is the user's completed tour keys, sorted.
        If `active_org_id` is provided AND the caller has
        membership (or is superadmin), also attach `_active_organization_id`
        and `_active_permissions` for the serializer to render. Soft-fail:
        invalid `active_org_id` results in both attributes being None (NOT 403).
        """
        User = get_user_model()  # noqa: N806
        user = User.objects.get(pk=user.pk)
        user._profile_memberships = self._get_memberships(user, api_key_org_id)
        # Sorted in Python: the database collation may order hyphenated keys differently.
        user._completed_tours = sorted(
            UserTourProgress.objects.filter(user_id=user.pk).values_list("tour_key", flat=True)
        )

        user._active_organization_id = None
        user._active_permissions = None
        if active_org_id is not None:
            # Confirm the org exists; missing orgs soft-fail (returns nulls).
            if not Organization.objects.filter(pk=active_org_id).exists():
                return user
            try:
                effective = self._permission_resolver.resolve(user=user, org_id=active_org_id)
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

    def _get_memberships(self, user, api_key_org_id: int | None):
        """Membership rows to render in the profile.

        Normal user: their real active memberships (with their real role),
        ordered by joined_at. Superadmin: every active organization with the
        built-in Superadmin role, ordered by name. Either narrowed to
        `api_key_org_id` when given.
        """
        if getattr(user, "is_superadmin", False):
            superadmin_role = Role.objects.get(
                name=BuiltInRole.SUPERADMIN, is_built_in=True, org__isnull=True
            )
            orgs = Organization.objects.filter(is_active=True)
            if api_key_org_id is not None:
                orgs = orgs.filter(pk=api_key_org_id)
            return [
                {"id": None, "org": org, "role": superadmin_role, "joined_at": None}
                for org in orgs.order_by(Lower("name"))
            ]
        memberships = OrganizationUser.objects.filter(user=user, org__is_active=True)
        if api_key_org_id is not None:
            memberships = memberships.filter(org_id=api_key_org_id)
        return memberships.select_related("org", "role").order_by("joined_at")

    # ---- profile field updates ----

    def update_profile(self, user, changes: dict):
        update_fields = []
        if "display_name" in changes:
            user.display_name = changes["display_name"]
            update_fields.append("display_name")
        if "custom_shortcuts" in changes:
            user.custom_shortcuts = changes["custom_shortcuts"]
            update_fields.append("custom_shortcuts")
        if not update_fields:
            return user

        user.save(update_fields=[*update_fields, "updated_at"])
        if "display_name" in changes:
            logger.info(
                "profile.display_name_updated user_id={} cleared={}",
                user.id,
                changes["display_name"] is None,
            )
        if "custom_shortcuts" in changes:
            logger.info(
                "profile.custom_shortcuts_updated user_id={} custom={} overrides={}",
                user.id,
                len(changes["custom_shortcuts"]["custom"]),
                len(changes["custom_shortcuts"]["overrides"]),
            )
        return user

    def complete_tour(self, user, tour_key: str) -> None:
        """Record that the user finished or skipped the tour `tour_key`.

        Idempotent: the first completion time wins. Two calls racing for the
        same key (two tabs closing the tour at once) are settled by the unique
        constraint inside get_or_create: the loser reads the winner's row, so
        the first time stays and only one call logs. The limit is counted
        without a lock: racing calls for different new keys at the limit can
        each land, which overshoots it by at most that burst — it bounds
        storage, it is not a quota. `updated_at` is deliberately left alone:
        this is a UI preference, not a profile edit.

        Args:
            tour_key: Already validated by UserValidationService.validate_tour_key.

        Raises:
            TourLimitExceededError: `tour_key` is new and the user already
                completed TOURS_MAX_PER_USER tours.
        """
        completed_tour_keys = set(
            UserTourProgress.objects.filter(user_id=user.pk).values_list("tour_key", flat=True)
        )
        if tour_key in completed_tour_keys:
            return
        if len(completed_tour_keys) >= TOURS_MAX_PER_USER:
            raise TourLimitExceededError(
                detail=f"Maximum number of completed tours reached ({TOURS_MAX_PER_USER})."
            )
        _, created = UserTourProgress.objects.get_or_create(
            user_id=user.pk, tour_key=tour_key, defaults={"completed_at": timezone.now()}
        )
        if created:
            logger.info("profile.tour_completed user_id={} tour_key={}", user.pk, tour_key)

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

    def password_change_request(self, user, current_password: str) -> tuple[str, int]:
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

    def password_change_confirm(self, actor, ticket: str, new_password: str) -> TokenPair:
        """Step 2: consume ticket, write new password, revoke credentials, mint a fresh pair.

        The password write and the revocation of every live refresh token
        and existing personal API key share one transaction. The fresh pair is
        minted after it commits, so it is the only refresh token that survives.

        Dual binding: ticket must exist AND must belong to the calling
        actor. Mismatch surfaces as the same generic
        InvalidPasswordChangeTicketError so a third party cannot probe
        whether a ticket exists for another user. A rejected password raises
        FormValidationError and leaves the ticket unconsumed.
        """
        # Consuming the ticket is a Redis GETDEL the transaction below cannot
        # roll back, so the account-aware check runs first, against the actor
        # the ticket must belong to.
        self._password_writer.validate(actor, new_password)
        target = self._password_change_ticket.consume(ticket)
        if target is None or actor is None or target.id != actor.id:
            logger.info(
                "profile.password_change_confirm_rejected actor_id={}",
                getattr(actor, "id", None),
            )
            raise InvalidPasswordChangeTicketError()
        with transaction.atomic():
            self._password_writer.set(target, new_password)
            self._credential_revoker.revoke_all_credentials_for_user(target)
        logger.info("profile.password_change_confirmed user_id={}", target.id)
        return TokenPair.for_user(target)
