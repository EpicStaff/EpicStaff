from django.db import models

from tables.models.user import User


class UserGraphViewSettings(models.Model):
    """One user's own flow-editor settings for one flow, over their account preferences.

    `settings` holds only the overridden keys of the `flow_editor` preference section.
    Personal view state, not part of the flow: other users never see it, and it is
    deliberately left out of flow copy, export and import. Not an `OrgScopedModel`: the
    organization is the graph's.

    The row stays while its flow is in the recycle bin, comes back with a restore, and is
    deleted with the flow's purge or with the user.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="graph_view_settings")
    graph = models.ForeignKey("Graph", on_delete=models.CASCADE, related_name="user_view_settings")
    settings = models.JSONField(default=dict, blank=True)

    soft_delete_kept_link_fields = ("graph",)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "graph"], name="unique_user_graph_view_settings"
            ),
        ]
