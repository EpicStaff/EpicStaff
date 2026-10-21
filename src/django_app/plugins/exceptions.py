"""Plugin errors. Each `default_code` is a stable API code the frontend maps to a message."""

from collections.abc import Iterable

from epicstaff_plugin.problems import Problem
from utils.exceptions import CustomAPIExeption


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


class PluginFeatureUnavailableError(_ProblemListError):
    """The package declares a part this EpicStaff cannot run yet (a backend or a database)."""

    status_code = 400
    default_detail = "The plugin needs a feature this EpicStaff does not offer yet."
    default_code = "plugin_feature_unavailable"


class InvalidSignatureError(CustomAPIExeption):
    status_code = 400
    default_detail = "The package signature is invalid."
    default_code = "invalid_signature"


class PackageTooLargeError(CustomAPIExeption):
    status_code = 413
    default_detail = "The plugin package is too large."
    default_code = "package_too_large"


class PluginUpgradeUnavailableError(CustomAPIExeption):
    status_code = 409
    default_detail = (
        "This plugin is already installed; installing a new version is not available yet."
    )
    default_code = "plugin_upgrade_unavailable"


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
