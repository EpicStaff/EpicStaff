from django.core.validators import RegexValidator
from django.db import models


class WebhookTrigger(models.Model):
    path = models.CharField(
        max_length=255,
        validators=[
            RegexValidator(
                regex=r"^[a-zA-Z0-9]{1}[a-zA-Z0-9-_]*$",
                message="Path may only contain letters, numbers, hyphens, and underscores, and must start with a letter or number.",
            )
        ],
        unique=True,
    )

    def __str__(self):
        return self.path
