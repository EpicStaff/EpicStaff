from django.db import models


class PluginSigningKey(models.Model):
    """An Ed25519 key EpicStaff signs gateway contexts with.

    The newest key that is not retired signs; a retired key stays in the published JWKS for
    a while so contexts it signed just before a rotation still verify. The private key is
    stored only encrypted (`secret_encryption` of the base64 of its raw 32-byte seed);
    `public_key` is the base64url of the raw 32-byte public key (a JWK's `x`).
    """

    kid = models.CharField(max_length=16, unique=True)
    private_key_encrypted = models.TextField()
    public_key = models.CharField(max_length=43)
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.kid
