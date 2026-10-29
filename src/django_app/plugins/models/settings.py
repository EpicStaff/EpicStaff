from django.conf import settings
from django.db import models
from django.db.models import Q

from plugins.models.plugin import Plugin

SETTING_PER_PLUGIN_CONSTRAINT = "plugins_setting_value_plugin_key_uniq"


class PluginSettingValue(models.Model):
    """A value the SuperAdmin set for one of a plugin's manifest settings.

    Settings are deployment-wide: one value per plugin and key. A secret is stored only
    encrypted (`tables.services.secrets.secret_encryption`), with its last characters in
    `tail` for display; every other type is stored as plain JSON in `value`. A setting
    without a row is unset (its manifest default applies, if any).
    """

    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE, related_name="setting_values")
    key = models.CharField(max_length=64)
    value = models.JSONField(null=True, blank=True)
    encrypted_value = models.TextField(null=True, blank=True)
    tail = models.CharField(max_length=4, null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plugin", "key"], name=SETTING_PER_PLUGIN_CONSTRAINT),
            models.CheckConstraint(
                condition=(
                    Q(value__isnull=False, encrypted_value__isnull=True)
                    | Q(value__isnull=True, encrypted_value__isnull=False)
                ),
                name="plugins_setting_value_plain_or_encrypted",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.plugin_id}.{self.key}"
