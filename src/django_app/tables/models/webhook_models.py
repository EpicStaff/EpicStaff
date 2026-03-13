from django.core.validators import RegexValidator
from django.db import models


class NgrokWebhookConfig(models.Model):
    class Region(models.TextChoices):
        US = ("us",)
        EU = ("eu",)
        AP = ("ap",)

    name = models.CharField(
        max_length=50,
        unique=True,
    )

    auth_token = models.CharField(
        max_length=255, help_text="Token from dashboard.ngrok.com", unique=True
    )

    domain = models.CharField(
        max_length=255, blank=True, null=True, help_text="Your domain"
    )

    region = models.CharField(max_length=2, choices=Region.choices, default=Region.EU)

    def get_webhook_url(self):
        if self.domain:
            return f"https://{self.domain}"
        return None


class WebhookTrigger(models.Model):
    path = models.CharField(
        max_length=255,
        validators=[
            RegexValidator(
                regex=r"^[a-zA-Z0-9]{1}[a-zA-Z0-9-_]*$",
                message="Path may only contain letters, numbers, hyphens, and underscores, and must start with a letter or number.",
            )
        ],
    )
    ngrok_webhook_config = models.ForeignKey(
        NgrokWebhookConfig,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
    )

    class Meta:
        unique_together = [("path", "ngrok_webhook_config")]

    def __str__(self):
        return self.path
