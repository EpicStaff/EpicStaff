from tables.exceptions import CustomAPIExeption


class FormValidationError(CustomAPIExeption):
    """Raised by AuthValidationService when one or more submitted fields
    fail validation. Carries a structured `errors` list (populated by the
    service) which `custom_exception_handler` surfaces under the `errors`
    key of the response body.

    Each entry in `errors` has shape:
        {"field": str, "value": Any, "reason": str}

    Sensitive submitted values (password, refresh, token) are redacted by
    the service before they reach this exception.
    """

    status_code = 400
    default_detail = "Validation failed"
    default_code = "invalid"

    def __init__(self, errors: list[dict], detail=None):
        self.errors = errors
        super().__init__(detail=detail or self.default_detail)


class SetupAlreadyCompletedError(CustomAPIExeption):
    """Raised by FirstSetupService when setup has already been performed."""

    status_code = 409
    default_detail = "Setup has already been completed"
    default_code = "setup_already_completed"


class InvalidRefreshTokenError(CustomAPIExeption):
    """Raised by LogoutView when a refresh token is missing, malformed,
    expired, or already blacklisted."""

    status_code = 400
    default_detail = "Refresh token is invalid, expired, or already revoked."
    default_code = "invalid_or_expired_refresh"


class InvalidSseTicketError(CustomAPIExeption):
    """Raised when a ?ticket= query param on an SSE endpoint does not
    resolve to a live single-use ticket in cache."""

    status_code = 401
    default_detail = "Invalid or expired SSE ticket."
    default_code = "invalid_sse_ticket"


class InvalidOrExpiredTokenError(CustomAPIExeption):
    """Raised by PasswordRecoveryService.confirm_reset when the submitted
    token is unknown, already used, or past its TTL. The message is
    intentionally generic so the caller cannot distinguish between those
    cases and cannot probe token validity.
    """

    status_code = 400
    default_detail = "Reset token is invalid, expired, or already used."
    default_code = "invalid_or_expired_reset_token"


class InvalidCurrentPasswordError(CustomAPIExeption):
    """Raised by PasswordRecoveryService.change_password when the caller
    submits a wrong `current_password`. Flat 400 (not per-field) to avoid
    leaking whether the password was well-formed but wrong vs. malformed.
    """

    status_code = 400
    default_detail = "Current password is incorrect."
    default_code = "invalid_current_password"


class SuperadminRequiredError(CustomAPIExeption):
    """Raised when a non-superadmin attempts a superadmin-only action
    (admin password reset)."""

    status_code = 403
    default_detail = "Superadmin privileges are required for this action."
    default_code = "superadmin_required"


class UserNotFoundError(CustomAPIExeption):
    """Raised by admin-only flows (admin password reset, CLI reset) when
    the target user does not exist. Never used on anonymous/self-service
    flows — those always succeed silently to avoid enumeration.
    """

    status_code = 404
    default_detail = "User not found."
    default_code = "user_not_found"


class DefaultOrganizationConflictError(CustomAPIExeption):
    """
    Raised when creating the default Organization during first-setup hits a
    uniqueness conflict — e.g. a prior setup left an Organization row behind
    after all users were wiped (User delete cascades OrganizationUser but not
    Organization).
    """

    status_code = 409
    default_detail = (
        "Default organization already exists from a previous setup. "
        "Remove it manually or change DEFAULT_ORGANIZATION_NAME before retrying."
    )
    default_code = "default_organization_conflict"


class OrganizationNameConflictError(CustomAPIExeption):
    """Raised when creating or renaming an organization to a name that
    already exists (case-insensitive)."""

    status_code = 400
    default_detail = "An organization with this name already exists."
    default_code = "organization_name_conflict"


class LastActiveOrganizationError(CustomAPIExeption):
    """Raised when deactivating an organization would leave zero active
    organizations in the system. The system requires at least one active
    organization."""

    status_code = 400
    default_detail = (
        "Cannot deactivate the last active organization. At least one "
        "organization must remain active."
    )
    default_code = "last_active_organization"


class OrganizationNotFoundError(CustomAPIExeption):
    """Raised by OrganizationManagementService when an org id does not match
    any existing row. Surfaces as 404 with the project-standard envelope."""

    status_code = 404
    default_detail = "Organization not found."
    default_code = "organization_not_found"


class EmailAlreadyExistsError(CustomAPIExeption):
    """Raised by UserManagementService.create_user / add_membership when the
    submitted email already belongs to an existing user. Admin-gated endpoint
    so enumeration is not a concern."""

    status_code = 400
    default_detail = "A user with this email already exists."
    default_code = "email_already_exists"


class MembershipAlreadyExistsError(CustomAPIExeption):
    """Raised by UserManagementService.add_membership when a (user, org)
    pair already has an OrganizationUser row. Caught from IntegrityError
    fired by the DB-level UniqueConstraint."""

    status_code = 400
    default_detail = "This user is already a member of this organization."
    default_code = "membership_already_exists"


class LastSuperadminError(CustomAPIExeption):
    """Raised by UserManagementService.revoke_superadmin when revoking
    would leave zero (is_superadmin=True, is_active=True) users in the
    system."""

    status_code = 400
    default_detail = (
        "Cannot revoke superadmin from the last active superadmin. "
        "At least one active superadmin must remain."
    )
    default_code = "last_superadmin"


class LastOrgAdminError(CustomAPIExeption):
    """Raised by UserManagementService.remove_membership /change_role when
    the operation would leave the organization with zero Org Admins."""

    status_code = 400
    default_detail = (
        "Cannot remove or demote the last Org Admin of this organization. "
        "Promote another member to Org Admin first."
    )
    default_code = "last_org_admin"


class InvalidRoleAssignmentError(CustomAPIExeption):
    """Raised by UserManagementGuards.assert_role_is_assignable when the
    target role cannot be assigned via membership — either because it is
    the global Superadmin role (use grant-superadmin instead) or because
    it is a custom role belonging to a different organization."""

    status_code = 400
    default_detail = "This role cannot be assigned via membership."
    default_code = "invalid_role_assignment"


class RoleNotFoundError(CustomAPIExeption):
    """Raised by UserManagementService when a role_id does not match any
    existing Role row."""

    status_code = 404
    default_detail = "Role not found."
    default_code = "role_not_found"


class CannotSelfAssignError(CustomAPIExeption):
    """Raised by UserManagementService.assign_users when a non-superadmin
    caller includes their own user_id in the batch. Superadmins bypass
    this rule. Caller-relationship UX safety, not a system-integrity
    invariant — the single-row PATCH endpoint exists for deliberate
    self-modification."""

    status_code = 400
    default_detail = "You cannot include yourself in the assignment batch."
    default_code = "cannot_self_assign"


class InvalidPasswordChangeTicketError(CustomAPIExeption):
    """Raised by UserProfileService.password_change_confirm when the
    submitted ticket is unknown, already used, expired, or does not belong
    to the calling user. Generic message — does not distinguish the cases
    so a third party cannot probe whether a ticket exists."""

    status_code = 400
    default_detail = "Password-change ticket is invalid, expired, or already used."
    default_code = "invalid_password_change_ticket"


class InvalidAvatarError(CustomAPIExeption):
    """Raised by UserAvatarStorageService when Pillow verification fails
    or the decoded image format is outside settings.AVATAR_ALLOWED_FORMATS.
    Generic message — does not expose Pillow's internal reason."""

    status_code = 400
    default_detail = "Uploaded file is not a valid JPEG or PNG image."
    default_code = "invalid_avatar"


class AvatarTooLargeError(CustomAPIExeption):
    """Raised by UserAvatarStorageService when an avatar upload exceeds
    settings.AVATAR_MAX_BYTES. The default_detail is overridden at
    raise-site with the actual maximum so the FE can render it without
    hardcoding the number."""

    status_code = 400
    default_detail = "Avatar file exceeds the maximum allowed size."
    default_code = "avatar_too_large"


class BuiltInRoleImmutableError(CustomAPIExeption):
    """Raised by RoleManagementService when an edit or delete targets a
    Role with is_built_in=True. The four built-in roles (Superadmin,
    Org Admin, Member, Viewer) are immutable by spec."""

    status_code = 403
    default_detail = "Built-in roles cannot be edited or deleted."
    default_code = "built_in_role_immutable"


class OrgContextRequiredError(CustomAPIExeption):
    """Raised by OrgContextService when an endpoint requires an
    X-Organization-Id header (or URL kwarg) and neither is present
    or parseable as an int."""

    status_code = 400
    default_detail = "X-Organization-Id header is required for this endpoint."
    default_code = "org_context_required"


class OrgMembershipRequiredError(CustomAPIExeption):
    """Raised by OrgContextService when the caller is not a member of
    the requested org and is not superadmin. Membership against an
    inactive org also raises this."""

    status_code = 403
    default_detail = "You are not a member of this organization."
    default_code = "org_membership_required"


class OrganizationMembershipNotFound(CustomAPIExeption):
    """Raised when the X-Organization-Id header names an org the user is not a member of."""

    status_code = 403
    default_detail = "You are not a member of the specified organization."
    default_code = "organization_membership_not_found"


class UserHasNoOrganizationMembership(CustomAPIExeption):
    """Raised when the user belongs to no organization at all."""

    status_code = 400
    default_detail = "Your account is not a member of any organization."
    default_code = "no_organization_membership"


class OrganizationContextAmbiguous(CustomAPIExeption):
    """Raised when the user belongs to multiple orgs and no X-Organization-Id header is set."""

    status_code = 400
    default_detail = (
        "Multiple organization memberships; please specify X-Organization-Id header."
    )
    default_code = "organization_context_ambiguous"
