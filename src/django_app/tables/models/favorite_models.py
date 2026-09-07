from django.conf import settings
from django.db import models


class PythonCodeToolFavorite(models.Model):
    """Per-user favorite marker for a `PythonCodeTool`.

    Deliberately NOT org-scoped (not `OrgScopedModel`) — favoriting is a
    personal preference keyed off the user, not the org. Cross-org visibility
    of the underlying tool is still enforced by the viewset's org-scoped
    `get_queryset()`/`get_object()`, not by this model.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorited_python_code_tools",
    )
    tool = models.ForeignKey(
        "PythonCodeTool",
        on_delete=models.CASCADE,
        related_name="favorited_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "tool"],
                name="unique_python_tool_favorite",
            ),
        ]


class McpToolFavorite(models.Model):
    """Per-user favorite marker for an `McpTool`. See `PythonCodeToolFavorite`
    for the rationale on not being org-scoped."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorited_mcp_tools",
    )
    tool = models.ForeignKey(
        "McpTool",
        on_delete=models.CASCADE,
        related_name="favorited_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "tool"],
                name="unique_mcp_tool_favorite",
            ),
        ]
