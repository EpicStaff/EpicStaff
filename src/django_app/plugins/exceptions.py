from utils.exceptions import CustomAPIExeption


class InvalidPluginError(CustomAPIExeption):
    """The uploaded file is not a plugin this server accepts.

    `errors` lists every problem found as `{"loc": ..., "message": ...}`, so the
    install dialog can show them all at once.
    """

    status_code = 400
    default_detail = "The plugin file is invalid."
    default_code = "invalid_plugin"

    def __init__(self, errors: list[dict]):
        self.errors = errors
        summary = errors[0]["message"] if len(errors) == 1 else f"{len(errors)} problems found."
        super().__init__(detail=f"The plugin file is invalid: {summary}")


class InvalidPluginSecretsError(CustomAPIExeption):
    status_code = 400
    default_detail = "The secret values do not match the plugin's secret slots."
    default_code = "invalid_plugin_secrets"

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__(detail=self.default_detail)


class PluginAlreadyInstalledError(CustomAPIExeption):
    status_code = 409
    default_code = "plugin_already_installed"

    def __init__(self, plugin_id: str, installed_version: str):
        self.errors = [{"plugin_id": plugin_id, "installed_version": installed_version}]
        super().__init__(
            detail=(
                f"Plugin '{plugin_id}' {installed_version} is already installed "
                "in this organization."
            )
        )


class PluginResourceConflictError(CustomAPIExeption):
    """An org row the plugin would create already exists under the same name."""

    status_code = 409
    default_code = "plugin_resource_conflict"

    def __init__(self, conflicts: list[dict]):
        self.errors = conflicts
        super().__init__(detail="; ".join(conflict["message"] for conflict in conflicts))


class PluginInstallForbiddenError(CustomAPIExeption):
    """The installer could not create one of the bundled resource types directly."""

    status_code = 403
    default_code = "plugin_install_forbidden"

    def __init__(self, missing: list[dict]):
        self.errors = missing
        names = ", ".join(f"{item['resource_type']}:{item['action']}" for item in missing)
        super().__init__(
            detail=f"Installing this plugin needs permissions you do not have: {names}."
        )


class PluginDeleteForbiddenError(CustomAPIExeption):
    """The caller could not delete one of the resource types the uninstall would remove.

    Mirrors `PluginInstallForbiddenError`: `plugins:delete` alone must not remove
    flows, agents, secrets or files the caller could not delete directly.
    """

    status_code = 403
    default_code = "plugin_delete_forbidden"

    def __init__(self, missing: list[dict]):
        self.errors = missing
        names = ", ".join(f"{item['resource_type']}:{item['action']}" for item in missing)
        super().__init__(detail=f"Deleting this plugin needs permissions you do not have: {names}.")


class PluginSuspendedError(CustomAPIExeption):
    """The plugin is suspended, so nothing it installed may run or open.

    Raised by `PluginGuard` wherever a flow, agent or tool is about to run, and by
    the lifecycle actions that need a running plugin.
    """

    status_code = 409
    default_detail = "This plugin is suspended. Resume it first."
    default_code = "plugin_suspended"

    def __init__(self, plugin_name: str | None = None):
        detail = (
            f"Plugin '{plugin_name}' is suspended. Its flows, agents and tools cannot run "
            "until it is resumed."
            if plugin_name
            else self.default_detail
        )
        super().__init__(detail=detail)


class PluginNotReadyError(CustomAPIExeption):
    status_code = 409
    default_detail = "This plugin is not ready yet."
    default_code = "plugin_not_ready"


class PluginHasNoUiError(CustomAPIExeption):
    status_code = 409
    default_detail = "This plugin has no page to open."
    default_code = "plugin_has_no_ui"


class PluginNotRetryableError(CustomAPIExeption):
    status_code = 409
    default_detail = "Only a plugin that needs attention can be retried."
    default_code = "plugin_not_retryable"


class PluginDevModeDisabledError(CustomAPIExeption):
    """The instance does not run in plugin dev mode (settings.PLUGINS_DEV_MODE is off)."""

    status_code = 409
    default_detail = "Plugin dev mode is off on this EpicStaff instance."
    default_code = "plugin_dev_mode_disabled"


class InvalidPluginDevUiUrlError(CustomAPIExeption):
    status_code = 400
    default_detail = (
        "The dev server URL must be a plain http:// URL on localhost or 127.0.0.1, "
        "with an optional port and path and no query or fragment."
    )
    default_code = "invalid"
