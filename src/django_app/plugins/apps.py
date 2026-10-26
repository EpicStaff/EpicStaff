import sys

from django.apps import AppConfig


class PluginsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plugins"

    def ready(self):
        from rbac.governance.organization_deletion import register_participant
        from rbac.governance.role_assignment_checks import register_role_assignment_check
        from tables.services.run_admission import register_run_admission_check

        from plugins import checks  # noqa: F401
        from plugins.access.role_assignment_check import PluginRoleAssignmentCheck
        from plugins.organization_deletion import PluginsOrganizationDeletion
        from plugins.ownership.ownership_recorder import connect_ownership_recorder
        from plugins.runs.run_guard import PluginRunGuard

        # Deleting an organization asks each plugin granted to it to delete its data there;
        # the participant also names the plugin rows of the delete report.
        register_participant(PluginsOrganizationDeletion())
        # Assigning a role must not hand out plugin actions beyond the assigner's own.
        register_role_assignment_check(PluginRoleAssignmentCheck())
        connect_ownership_recorder()
        # Whether or not the plugin platform is on: switching it off must never let a
        # suspended plugin's resources run again.
        register_run_admission_check(PluginRunGuard())

        # Grace periods and deletions run whether or not the platform is on: a grace period
        # is a promise about EpicStaff's data. Only under a web server, never in a migration
        # or a test (the same detection as the tables app's schedulers).
        argv0 = sys.argv[0] if sys.argv else ""
        is_web_server = (
            "runserver" in sys.argv
            or "gunicorn" in argv0
            or "uvicorn" in argv0
            or "daphne" in argv0
        )
        if is_web_server:
            from plugins.lifecycle.retention_scheduler import start_plugin_retention_if_owner

            start_plugin_retention_if_owner()
