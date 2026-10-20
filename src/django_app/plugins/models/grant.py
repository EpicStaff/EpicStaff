from django.db import models
from rbac.models import OrgScopedModel

from plugins.models.enums import GrantState
from plugins.models.plugin import Plugin

GRANT_PER_ORGANIZATION_CONSTRAINT = "plugins_grant_plugin_org_uniq"


class PluginGrant(OrgScopedModel):
    """A plugin given to one organization by a SuperAdmin.

    The only organization-owned plugin row: `org` is NOT NULL in the database, and
    `created_by` is the SuperAdmin who granted it. Only `active` grants make a plugin
    usable in the organization.
    """

    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE, related_name="grants")
    state = models.CharField(max_length=32, choices=GrantState.choices)
    suspended_at = models.DateTimeField(null=True, blank=True)
    purge_after = models.DateTimeField(null=True, blank=True)
    last_hook_error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["plugin", "org"], name=GRANT_PER_ORGANIZATION_CONSTRAINT
            ),
        ]

    def __str__(self) -> str:
        return f"{self.plugin_id} in org {self.org_id}"
