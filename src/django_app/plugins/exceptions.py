"""Plugin errors. Each `default_code` is a stable API code the frontend maps to a message."""

from collections.abc import Iterable
from typing import TYPE_CHECKING

from epicstaff_plugin.problems import Problem
from rest_framework.exceptions import AuthenticationFailed
from tables.services.run_admission import RunAdmissionRefusedError
from utils.exceptions import CustomAPIExeption

from plugins.models.enums import GrantState

if TYPE_CHECKING:
    from plugins.runs.owned_resource_index import BlockingOwner


class _ProblemListError(CustomAPIExeption):
    """An error whose `errors` lists every `{loc, message}` problem found."""

    def __init__(self, problems: Iterable[Problem]):
        self.errors = [problem.as_dict() for problem in problems]
        summary = (
            self.errors[0]["message"]
            if len(self.errors) == 1
            else f"{len(self.errors)} problems found."
        )
        super().__init__(detail=f"{self.default_detail} {summary}")


class InvalidPluginError(_ProblemListError):
    status_code = 400
    default_detail = "The plugin package is invalid."
    default_code = "invalid_plugin"


class InvalidSignatureError(CustomAPIExeption):
    status_code = 400
    default_detail = "The package signature is invalid."
    default_code = "invalid_signature"


class PackageTooLargeError(CustomAPIExeption):
    status_code = 413
    default_detail = "The plugin package is too large."
    default_code = "package_too_large"


class PluginUpgradeUnavailableError(_ProblemListError):
    """The package cannot upgrade the installed plugin: it drops the backend or the database,
    or changes a migration file that is already applied; each problem says which."""

    status_code = 409
    default_detail = "This package cannot upgrade the installed plugin."
    default_code = "plugin_upgrade_unavailable"


class PluginVersionNotNewerError(CustomAPIExeption):
    """The package's version is not newer than the plugin's latest approved version."""

    status_code = 409
    default_detail = "This version is not newer than the installed one."
    default_code = "plugin_version_not_newer"

    def __init__(self, version: str, installed_version: str, latest_version: str):
        if latest_version == installed_version:
            detail = f"{version} is not newer than the installed {installed_version}"
        else:
            detail = f"{version} is not newer than {latest_version}, the version being installed"
        super().__init__(detail=detail)
        self.extra_response_data = {
            "installed_version": installed_version,
            "latest_version": latest_version,
        }


class PluginNotUpgradableError(CustomAPIExeption):
    status_code = 409
    default_detail = "The plugin cannot be upgraded now."
    default_code = "plugin_not_upgradable"


class ReviewOutdatedError(CustomAPIExeption):
    """The approval names another package than the one the review was computed against."""

    status_code = 409
    default_detail = "The plugin changed since this review was loaded. Review it again."
    default_code = "review_outdated"


class AccessGrowthNotAcknowledgedError(CustomAPIExeption):
    status_code = 400
    default_detail = "This version asks for new access. Approve the new access to upgrade."
    default_code = "access_growth_not_acknowledged"


class UpgradeNotCancellableError(CustomAPIExeption):
    status_code = 409
    default_detail = "This upgrade cannot be cancelled now."
    default_code = "upgrade_not_cancellable"


class UpgradeNotRetryableError(CustomAPIExeption):
    status_code = 409
    default_detail = "No failed upgrade of this plugin to retry."
    default_code = "upgrade_not_retryable"


class PluginUpgradeOpenError(CustomAPIExeption):
    status_code = 409
    default_detail = "The plugin is being upgraded. Cancel the upgrade first, or delete the plugin."
    default_code = "plugin_upgrade_open"


class BackupNotFoundError(CustomAPIExeption):
    status_code = 404
    default_detail = "Backup not found."
    default_code = "backup_not_found"


class RestoreNotAllowedError(CustomAPIExeption):
    status_code = 409
    default_detail = "This backup cannot be restored now."
    default_code = "restore_not_allowed"


class InvalidRestorePhraseError(CustomAPIExeption):
    status_code = 400
    default_detail = "Type the phrase exactly as shown to restore the backup."
    default_code = "invalid_restore_phrase"


class UpgradeNotFoundError(CustomAPIExeption):
    status_code = 404
    default_detail = "Upgrade not found."
    default_code = "upgrade_not_found"


class UpgradeNotCurrentError(CustomAPIExeption):
    """The node asked to move an upgrade that is not open, has failed, or is in another stage."""

    status_code = 409
    default_detail = "The upgrade cannot move to this stage now."
    default_code = "upgrade_not_current"


class InvalidUpgradeAdvanceError(_ProblemListError):
    status_code = 400
    default_detail = "The upgrade request is invalid."
    default_code = "invalid_upgrade_advance"


class PluginPackageNotFoundError(CustomAPIExeption):
    status_code = 404
    default_detail = "Plugin package not found."
    default_code = "plugin_package_not_found"


class PackageNotPendingError(CustomAPIExeption):
    status_code = 409
    default_detail = "The package is not waiting for review."
    default_code = "package_not_pending"


class UntrustedNotAcknowledgedError(CustomAPIExeption):
    status_code = 400
    default_detail = "Approving an untrusted package needs untrusted_acknowledged set to true."
    default_code = "untrusted_not_acknowledged"


class PluginNotFoundError(CustomAPIExeption):
    status_code = 404
    default_detail = "Plugin not found."
    default_code = "plugin_not_found"


class PluginNotRunningError(CustomAPIExeption):
    status_code = 409
    default_detail = "The plugin is not running."
    default_code = "plugin_not_running"


class PluginAlreadyGrantedError(CustomAPIExeption):
    status_code = 409
    default_detail = "The plugin is already granted to this organization."
    default_code = "plugin_already_granted"


class OrganizationInactiveError(CustomAPIExeption):
    status_code = 409
    default_detail = "The organization is inactive."
    default_code = "organization_inactive"


class PackageFileMismatchError(CustomAPIExeption):
    """The stored package file is gone or is not the file that was reviewed."""

    status_code = 409
    default_detail = (
        "The stored package file is missing or differs from the reviewed one. "
        "Upload the package again."
    )
    default_code = "package_file_mismatch"


class InvalidPluginRolePermissionsError(_ProblemListError):
    """A Roles-matrix write names a plugin or an action the role's organization cannot have."""

    status_code = 400
    default_detail = "The role's plugin permissions are invalid."
    default_code = "invalid_plugin_role_permissions"


class PluginHasNoBackendError(CustomAPIExeption):
    status_code = 409
    default_detail = "The plugin has no backend."
    default_code = "plugin_has_no_backend"


class InvalidPluginSettingsError(_ProblemListError):
    status_code = 400
    default_detail = "The plugin settings are invalid."
    default_code = "invalid_plugin_settings"


class InvalidPluginLimitsError(_ProblemListError):
    status_code = 400
    default_detail = "The plugin limits are invalid."
    default_code = "invalid_plugin_limits"


class NoPluginNodeError(CustomAPIExeption):
    """A package with a backend needs a plugin node to run on, and none is registered."""

    status_code = 409
    default_detail = (
        "No plugin node named PLUGINS_NODE_NAME is registered, so a plugin with a backend "
        "cannot run. EpicStaff registers it at start-up (manage.py seed_plugin_node): restart "
        "EpicStaff, and check that PLUGINS_NODE_NAME has not changed since the node was set up."
    )
    default_code = "no_plugin_node"


class NoPluginDatabaseServerError(CustomAPIExeption):
    """A package with a database needs a database server for it, and none is registered."""

    status_code = 409
    default_detail = (
        "No plugin database server is registered, so a plugin with a database cannot be "
        "approved. EpicStaff registers it at start-up while plugins are on (manage.py "
        "seed_plugin_node): restart EpicStaff with PLUGINS_ENABLED=true."
    )
    default_code = "no_plugin_database_server"


class PluginNodeFullError(CustomAPIExeption):
    """Every port or Unix user id of the plugin node is taken by another plugin."""

    status_code = 409
    default_detail = "The plugin node has no free port or user id left for another plugin."
    default_code = "plugin_node_full"


class NodeNotAuthenticatedError(CustomAPIExeption):
    status_code = 401
    default_detail = "The plugin node key is missing or wrong."
    default_code = "node_not_authenticated"


class PlacementNotFoundError(CustomAPIExeption):
    status_code = 404
    default_detail = "Placement not found."
    default_code = "placement_not_found"


class InvalidNodeReportError(_ProblemListError):
    status_code = 400
    default_detail = "The node report is invalid."
    default_code = "invalid_node_report"


class SigningKeyMissingError(CustomAPIExeption):
    """No context-signing key exists: `seed_plugin_node` creates the first one at start-up."""

    status_code = 503
    default_detail = (
        "EpicStaff has no plugin signing key yet. Restart EpicStaff with plugins on, or run "
        "manage.py seed_plugin_node."
    )
    default_code = "signing_key_missing"


class InvalidAuthorizeRequestError(_ProblemListError):
    """A plugin authorize request with a missing, repeated, unknown or malformed parameter.

    Answered as JSON, never as a redirect: with a broken request there is nowhere safe to send
    the browser.
    """

    status_code = 400
    default_detail = "The plugin login request is invalid."
    default_code = "invalid_authorize_request"


class InvalidTokenRequestError(_ProblemListError):
    """A token exchange whose JSON body is not exactly `{code, code_verifier}` of the right form."""

    status_code = 400
    default_detail = "The request body is invalid."
    default_code = "invalid"


class InvalidGrantError(CustomAPIExeption):
    """The code is unknown, expired or used, or the verifier or `Origin` does not match it."""

    status_code = 400
    default_detail = "The login code is invalid, expired or already used."
    default_code = "invalid_grant"


class PluginAccessDeniedError(CustomAPIExeption):
    """The person lost the right to use the plugin between the login and the code exchange."""

    status_code = 403
    default_detail = "You do not have access to this plugin in this organization."
    default_code = "plugin_access_denied"


class PluginOriginRefusedError(CustomAPIExeption):
    """A request from a plugin page to anything but the plugin token exchange (or authorize)."""

    status_code = 403
    default_detail = "Plugin pages cannot call EpicStaff's API."
    default_code = "plugin_origin_refused"


class ServiceAccountNotAuthenticatedError(CustomAPIExeption, AuthenticationFailed):
    """A `PluginKey` that is unknown, no longer valid, or sent from outside the plugins network.

    The same answer for every reason, so a caller learns nothing about a key it does not hold.
    """

    status_code = 401
    default_detail = "The plugin service-account key is missing, invalid or no longer valid."
    default_code = "service_account_not_authenticated"


class InvalidOnBehalfOfError(CustomAPIExeption):
    status_code = 400
    default_detail = "X-EpicStaff-On-Behalf-Of must be a user id: a positive whole number."
    default_code = "invalid_on_behalf_of"


class OnBehalfOfNotAllowedError(CustomAPIExeption):
    """The named person may not use the plugin in its organization, whatever the reason."""

    status_code = 403
    default_detail = "The plugin cannot act on behalf of this person."
    default_code = "on_behalf_of_not_allowed"


class PersonNotFoundError(CustomAPIExeption):
    status_code = 404
    default_detail = "Person not found."
    default_code = "person_not_found"


class GrantNotFoundError(CustomAPIExeption):
    status_code = 404
    default_detail = "Grant not found."
    default_code = "grant_not_found"


class HookNotRetryableError(CustomAPIExeption):
    status_code = 409
    default_detail = "Only a grant whose install hook failed can retry it."
    default_code = "hook_not_retryable"


class GrantNotSuspendableError(CustomAPIExeption):
    status_code = 409
    default_detail = "The grant cannot be suspended in its current state."
    default_code = "grant_not_suspendable"


class GrantNotSuspendedError(CustomAPIExeption):
    status_code = 409
    default_detail = "The grant is not suspended."
    default_code = "grant_not_suspended"


# How a refused run names the state of the grant that blocks it; every other state is "not active".
_GRANT_STATE_WORDS = {
    GrantState.SUSPENDED: "suspended",
    GrantState.UPGRADING: "being upgraded",
}


class PluginSuspendedError(RunAdmissionRefusedError):
    """A run would use something a plugin owns, and the plugin is not active in the organization.

    Names the plugin and the organization, never the resource: the caller may not be allowed to
    see which of the plugin's rows the run reaches.
    """

    status_code = 409
    default_detail = "This run uses resources of a plugin that is not active in this organization."
    default_code = "plugin_suspended"

    def __init__(self, owner: "BlockingOwner", organization_id: int):
        state = _GRANT_STATE_WORDS.get(owner.grant_state, "not active")
        super().__init__(
            detail=(
                f'This run uses resources of the plugin "{owner.plugin_name}", which is {state} '
                "in this organization."
            )
        )
        self.extra_response_data = {
            "plugin": {"identifier": owner.plugin_identifier, "name": owner.plugin_name},
            "organization": {"id": organization_id},
        }
        since = int(owner.since.timestamp()) if owner.since is not None else 0
        # Equal for every refusal of one episode, so a trigger logs it once; a new suspension
        # of the same grant (a new `since`) logs again.
        self.log_key = (
            f"{owner.plugin_identifier}:{owner.grant_id or 'none'}:"
            f"{owner.grant_state or 'removed'}:{since}"
        )


class HookJobNotFoundError(CustomAPIExeption):
    status_code = 404
    default_detail = "Hook job not found."
    default_code = "hook_job_not_found"


class HookJobNotClaimableError(CustomAPIExeption):
    """The job is not waiting, its plugin is not running, or its grant is gone or moved on."""

    status_code = 409
    default_detail = "The hook job cannot be claimed now."
    default_code = "hook_job_not_claimable"


class HookJobNotRunningError(CustomAPIExeption):
    """A result for a job that is not running, or for another attempt than the running one."""

    status_code = 409
    default_detail = "The hook job is not running this attempt."
    default_code = "hook_job_not_running"


class InvalidHookResultError(_ProblemListError):
    status_code = 400
    default_detail = "The hook result is invalid."
    default_code = "invalid_hook_result"


class InvalidPurgePhraseError(CustomAPIExeption):
    """The confirmation phrase of a permanent delete is missing or not the expected one."""

    status_code = 400
    default_detail = "The confirmation text does not match."
    default_code = "invalid_purge_phrase"


class GrantNotPurgeableError(CustomAPIExeption):
    status_code = 409
    default_detail = "The grant's data is already being deleted."
    default_code = "grant_not_purgeable"


class PluginNotUninstallableError(CustomAPIExeption):
    status_code = 409
    default_detail = "Only a provisioning, running or failed plugin can be uninstalled."
    default_code = "plugin_not_uninstallable"


class PluginNotUninstallingError(CustomAPIExeption):
    status_code = 409
    default_detail = "Only an uninstalled plugin can be reinstalled."
    default_code = "plugin_not_uninstalling"


class PluginNotPurgeableError(CustomAPIExeption):
    status_code = 409
    default_detail = "The plugin cannot be deleted in its current state."
    default_code = "plugin_not_purgeable"


class PluginUninstallingError(CustomAPIExeption):
    """A change refused because the plugin is uninstalled or being deleted."""

    status_code = 409
    default_detail = "The plugin is uninstalled or being deleted."
    default_code = "plugin_uninstalling"


class RemovalNotRetryableError(CustomAPIExeption):
    status_code = 409
    default_detail = "Only a removal the plugin node reported as failed can be retried."
    default_code = "removal_not_retryable"


class OrgRemovedHookNotRetryableError(CustomAPIExeption):
    status_code = 409
    default_detail = "The data removal cannot be retried in its current state."
    default_code = "org_removed_hook_not_retryable"


class OrgRemovedHookNotSkippableError(CustomAPIExeption):
    status_code = 409
    default_detail = "Only a waiting or failed data removal can be skipped."
    default_code = "org_removed_hook_not_skippable"
