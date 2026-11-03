from django.conf import settings
from django.db import models

from proxies.models import AbstractBinding


class SandboxVenvBinding(AbstractBinding):
    # Favoriting is personal, so the mark belongs to a user and a venv together, not to
    # the binding alone: one organization's members each have their own.
    favorited_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="favorited_venvs",
        blank=True,
    )
