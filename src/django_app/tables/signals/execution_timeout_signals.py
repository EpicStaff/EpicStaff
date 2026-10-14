from django.apps import apps as installed_apps
from tables.services.execution_timeout_ceiling_service import clamp_stored_execution_timeouts


def clamp_execution_timeouts_after_migrate(sender, using, apps=None, **kwargs):
    """Connected in `TablesConfig.ready()` with `sender` set to the tables app config,
    so it runs once per `migrate` of a database (every django_app start).

    `migrate` passes the post-migration schema as `apps`; `flush` sends the signal
    without it, and then the database has the installed schema.
    """
    clamp_stored_execution_timeouts(apps or installed_apps, using)
