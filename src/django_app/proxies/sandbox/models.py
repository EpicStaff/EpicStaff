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


class SandboxCustomLibraryBinding(AbstractBinding):
    """Which organization may reach one of the sandbox's custom libraries.

    The library's wheels have no binding of their own: the sandbox addresses a
    wheel only under its library and checks the pair, so a wheel is reachable
    exactly where the library is, and this binding is what scopes both.
    """
