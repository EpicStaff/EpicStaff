from django.db import models


class SessionCallback(models.Model):
    """Where to POST a session's terminal result, and how delivery is going.

    Created with the session (`registered`), filled by the Redis status listener
    on a terminal status (`pending`), then delivered by the `send_session_callbacks`
    command. `encrypted_secret` is cleared once the row is delivered or failed.
    """

    class Status(models.TextChoices):
        REGISTERED = "registered"
        PENDING = "pending"
        DELIVERED = "delivered"
        FAILED = "failed"

    session = models.OneToOneField("Session", on_delete=models.CASCADE, related_name="callback")
    url = models.URLField(max_length=2048)
    # Fernet encryptedtext of the HMAC signing secret (SecretEncryption); decrypted
    # only by the sender, to sign a delivery. Cleared once delivered or failed.
    encrypted_secret = models.TextField(blank=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.REGISTERED, db_index=True
    )
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
