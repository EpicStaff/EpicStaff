from django.conf import settings
from django.db import models


class OrgScopedModel(models.Model):
    """Abstract model giving a resource a single owning organization + a creator.

    `org` stays nullable so each phase can add the field to its
    models without forcing a NOT NULL on models that have not been backfilled yet.
    Non-null is enforced per table at the DB layer (RunSQL ALTER ... SET NOT NULL)
    after the backfill migration, and by the viewset mixin always stamping `org`.
    """

    org = models.ForeignKey(
        "Organization",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
        null=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        abstract = True
        indexes = [models.Index(fields=["org"])]
