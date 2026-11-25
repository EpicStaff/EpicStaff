from django.conf import settings
from django.db import models

from ai_models.models.llm_models import LLMModel


class LLMModelFavorite(models.Model):
    """Per-user favorite marker for an `LLMModel`, a catalog model or a custom one.

    Deliberately NOT org-scoped, as `tables.PythonCodeToolFavorite`: favoriting is a
    personal preference keyed off the user, not the org. Cross-org visibility of the
    model is still enforced where favorites are read and written
    (`ai_models.services.model_favorites`): only rows the active organization sees count.

    No soft-delete fields, unlike the tool favorites: an `LLMModel` never goes to the
    recycle bin, so its favorites have nothing to be restored with.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorited_llm_models",
    )
    llm_model = models.ForeignKey(
        LLMModel,
        on_delete=models.CASCADE,
        related_name="favorited_by",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "llm_model"],
                name="unique_llm_model_favorite",
            ),
        ]
