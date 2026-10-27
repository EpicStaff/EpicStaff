from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.db.models import Q

from plugins.models.plugin import Plugin

# Ports below 1024 are the host's privileged ports; the platform never routes to them.
MIN_DEVELOPMENT_PORT = 1024
MAX_DEVELOPMENT_PORT = 65535


def _port_in_range(field: str) -> Q:
    return Q(**{f"{field}__isnull": True}) | Q(
        **{f"{field}__gte": MIN_DEVELOPMENT_PORT, f"{field}__lte": MAX_DEVELOPMENT_PORT}
    )


class PluginDevelopmentTarget(models.Model):
    """Where plugin development mode serves a plugin from: ports on the author's machine.

    Deployment-wide and set only by a SuperAdmin. `backend_port` takes the plugin's backend
    requests, `spa_port` its page; the host is always `host.docker.internal`, never stored.
    The row is inert while `PLUGINS_DEV_MODE` is off, and is deleted with its plugin.
    """

    plugin = models.OneToOneField(
        Plugin, on_delete=models.CASCADE, related_name="development_target"
    )
    backend_port = models.PositiveIntegerField(null=True, blank=True)
    spa_port = models.PositiveIntegerField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # A target with no port routes nothing: stopping development deletes the row.
            models.CheckConstraint(
                condition=Q(backend_port__isnull=False) | Q(spa_port__isnull=False),
                name="plugins_development_target_has_port",
            ),
            models.CheckConstraint(
                condition=_port_in_range("backend_port"),
                name="plugins_development_backend_port_range",
            ),
            models.CheckConstraint(
                condition=_port_in_range("spa_port"),
                name="plugins_development_spa_port_range",
            ),
        ]

    def __str__(self) -> str:
        return f"development target of plugin {self.plugin_id}"


def development_target_of(plugin: Plugin) -> PluginDevelopmentTarget | None:
    """The plugin's stored target, or None; from `select_related` when it was loaded so."""
    try:
        return plugin.development_target
    except ObjectDoesNotExist:
        return None
