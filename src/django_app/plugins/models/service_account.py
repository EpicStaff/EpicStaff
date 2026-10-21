from django.db import models
from django.db.models import Q

from plugins.models.enums import GrantState
from plugins.models.grant import PluginGrant

ONE_CURRENT_KEY_PER_ACCOUNT_CONSTRAINT = "plugins_sa_key_one_current_per_account"
# The grant states in which a plugin's service account holds keys, so its backend can call
# EpicStaff in the organization: while the install hook runs, and once the grant is active.
KEY_HOLDING_GRANT_STATES = (GrantState.GRANTING, GrantState.ACTIVE)


class PluginServiceAccountQuerySet(models.QuerySet):
    def key_holding(self) -> "PluginServiceAccountQuerySet":
        """Accounts that get a key: not revoked, of a key-holding grant in an active organization."""
        return self.filter(
            revoked_at__isnull=True,
            grant__state__in=KEY_HOLDING_GRANT_STATES,
            grant__org__is_active=True,
        )


class PluginServiceAccount(models.Model):
    """The identity a plugin's backend calls EpicStaff with in one organization.

    One per grant of a plugin whose current package has a backend, created with the grant.
    It holds no rights of its own: the plugin's declared access, in the grant's
    organization only, is everything it may do. `last_used_at` is when any of its keys last
    authenticated, written at most once a minute.
    """

    grant = models.OneToOneField(
        PluginGrant, on_delete=models.CASCADE, related_name="service_account"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    objects = PluginServiceAccountQuerySet.as_manager()

    def __str__(self) -> str:
        return f"service account of grant {self.grant_id}"


class PluginServiceAccountKey(models.Model):
    """A key of a service account; only its sha256 is stored.

    The current key has no `expires_at`. Minting a new one gives the previous current key ten
    more minutes and revokes every older one, so at most two keys of an account are valid.
    """

    # Read by rbac's gates (`is_plugin_credential`) without importing this app.
    is_plugin_credential = True

    service_account = models.ForeignKey(
        PluginServiceAccount, on_delete=models.CASCADE, related_name="keys"
    )
    prefix = models.CharField(max_length=12)
    key_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["service_account"],
                condition=Q(expires_at__isnull=True, revoked_at__isnull=True),
                name=ONE_CURRENT_KEY_PER_ACCOUNT_CONSTRAINT,
            ),
        ]
        indexes = [
            # Every mint reads an account's unrevoked keys (at most two), while revoked
            # ones pile up until they are pruned.
            models.Index(
                fields=["service_account"],
                condition=Q(revoked_at__isnull=True),
                name="plugins_sa_key_unrevoked",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.prefix}… of service account {self.service_account_id}"
