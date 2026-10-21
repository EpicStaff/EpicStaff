from functools import cached_property

from django.conf import settings
from django.db import models
from django.db.models import BooleanField, Count, Exists, ExpressionWrapper, OuterRef, Prefetch, Q
from epicstaff_plugin.contracts.manifest import PluginManifest

from plugins.models.enums import GrantState, PluginState, ReviewState, SignatureStatus, Trust

# Large columns a plugin list never shows.
PACKAGE_DETAIL_FIELDS = ("icon_bytes", "manifest")


class PluginQuerySet(models.QuerySet):
    def with_summary(self) -> "PluginQuerySet":
        """Load what a plugin summary shows in a fixed number of queries.

        Adds `grant_count` (active grants), `needs_attention` (an organization removed job
        failed for good, the node failed to remove the plugin, or a grant's data could not
        all be deleted yet) and `pending_packages` (a list holding the pending package, if
        any). The current package comes without its icon and manifest, the placement with it.
        """
        # Imported here: these modules import this one.
        from plugins.models.enums import PlacementRemovalState
        from plugins.models.grant import PluginGrant
        from plugins.models.hook_job import HookJobKind, HookJobState, PluginHookJob
        from plugins.models.node import PluginPlacement

        needs_attention = ExpressionWrapper(
            Exists(
                PluginHookJob.objects.filter(
                    plugin=OuterRef("pk"),
                    kind=HookJobKind.ORG_REMOVED,
                    state=HookJobState.FAILED,
                )
            )
            | Exists(
                PluginPlacement.objects.filter(
                    plugin=OuterRef("pk"), removal_state=PlacementRemovalState.FAILED
                )
            )
            | Exists(
                PluginGrant.objects.filter(
                    plugin=OuterRef("pk"),
                    state=GrantState.PURGING,
                    last_purge_error__isnull=False,
                )
            ),
            output_field=BooleanField(),
        )
        return (
            self.select_related("current_package", "placement")
            .defer(*(f"current_package__{field}" for field in PACKAGE_DETAIL_FIELDS))
            .annotate(
                grant_count=Count(
                    "grants", filter=Q(grants__state=GrantState.ACTIVE), distinct=True
                ),
                needs_attention=needs_attention,
            )
            .prefetch_related(
                Prefetch(
                    "packages",
                    queryset=PluginPackage.objects.filter(review_state=ReviewState.PENDING).only(
                        "id", "plugin_id", "version", "trust"
                    ),
                    to_attr="pending_packages",
                )
            )
        )


class Plugin(models.Model):
    """A plugin installed for the whole deployment.

    Deployment-wide, not organization-owned: only SuperAdmins manage plugins, and a
    `PluginGrant` gives one to an organization. The row exists from the first upload of its
    identifier; `current_package` is the approved package, None until the first approval.
    """

    identifier = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=500)
    state = models.CharField(
        max_length=32, choices=PluginState.choices, default=PluginState.UPLOADED
    )
    # RESTRICT, not PROTECT: deleting the plugin may still cascade to this package.
    current_package = models.ForeignKey(
        "plugins.PluginPackage",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="+",
    )
    # The SuperAdmin's lowered limits, by limit name; they can only lower what the manifest
    # asks for (plugins.configuration.limits).
    limit_overrides = models.JSONField(default=dict, blank=True)
    # Set by an uninstall: its data is kept until `purge_after`, then the plugin is deleted.
    uninstall_requested_at = models.DateTimeField(null=True, blank=True)
    purge_after = models.DateTimeField(null=True, blank=True)
    # When its deletion began; the row itself is deleted once the deletion is done.
    purge_started_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PluginQuerySet.as_manager()

    class Meta:
        indexes = [
            # The grace-period sweep asks for uninstalled plugins whose time is up.
            models.Index(fields=["state", "purge_after"], name="plugins_plugin_state_purge"),
        ]

    def __str__(self) -> str:
        return self.identifier


class PluginPackage(models.Model):
    """One uploaded `.esplugin` file of a plugin, with what its review needs.

    The file itself lives in the plugin package bucket under `storage_key`. `manifest` holds
    the validated manifest; the icon is copied out so the review and the public icon endpoint
    never open the package. At most one package per plugin is pending review.
    """

    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE, related_name="packages")
    version = models.CharField(max_length=64)
    sha256 = models.CharField(max_length=64)
    size = models.BigIntegerField()
    storage_key = models.CharField(max_length=255)
    manifest = models.JSONField()
    trust = models.CharField(max_length=16, choices=Trust.choices)
    signature_status = models.CharField(max_length=16, choices=SignatureStatus.choices)
    signer_key_id = models.CharField(max_length=16, null=True, blank=True)
    signer_key_name = models.CharField(max_length=64, null=True, blank=True)
    # The minisign public key (`RW...`) the signature verified with, as trusted when the
    # verdict was taken; set exactly when `trust` is trusted, so the plugin node checks the
    # signature with the key EpicStaff checked it with, whatever the trusted keys are today.
    signer_public_key = models.CharField(max_length=64, null=True, blank=True)
    review_state = models.CharField(
        max_length=16, choices=ReviewState.choices, default=ReviewState.PENDING
    )
    icon_bytes = models.BinaryField()
    icon_media_type = models.CharField(max_length=32)
    spa_file_count = models.PositiveIntegerField(default=0)
    spa_bytes = models.PositiveBigIntegerField(default=0)
    wheel_count = models.PositiveIntegerField(default=0)
    migration_count = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plugin", "version"], name="plugins_package_plugin_version_uniq"
            ),
            models.UniqueConstraint(
                fields=["plugin"],
                condition=Q(review_state=ReviewState.PENDING),
                name="plugins_package_one_pending_per_plugin",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.plugin_id}@{self.version}"

    @cached_property
    def parsed_manifest(self) -> PluginManifest:
        return PluginManifest.model_validate(self.manifest)
