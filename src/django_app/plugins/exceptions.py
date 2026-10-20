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
