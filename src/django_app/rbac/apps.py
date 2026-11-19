from django.apps import AppConfig


class RbacConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rbac"

    def ready(self):
        from tables.services.run_admission import register_run_admission_check

        from rbac.authorship import checks  # noqa: F401
        from rbac.governance.organization_run_admission import ActiveOrganizationRunCheck

        # rbac comes before plugins in INSTALLED_APPS, so this check runs first: a deactivated
        # organization is refused with one query, without the plugin guard walking the run.
        register_run_admission_check(ActiveOrganizationRunCheck())
