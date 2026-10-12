from django.apps import AppConfig


class RbacConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rbac"

    def ready(self):
        from rbac.authorship import checks  # noqa: F401
