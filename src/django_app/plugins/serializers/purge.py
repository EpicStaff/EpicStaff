"""What the SuperAdmin's delete, uninstall and data-removal endpoints answer."""

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from plugins.lifecycle.hook_job_service import retry_until
from plugins.lifecycle.org_removed_hooks import OrgRemovedJobAction, allowed_org_removed_job_actions
from plugins.lifecycle.purge_preview_service import PluginDataFate
from plugins.models import HookJobState, PluginHookJob
from plugins.serializers.suspension import (
    OwnedResourceCountSerializer,
    PreviewDefaultModelSerializer,
    PreviewFlowsSerializer,
    PreviewGrantSerializer,
    PreviewOrganizationSerializer,
    PreviewPluginSerializer,
    PreviewSessionListSerializer,
)


class VerificationPhraseSerializer(serializers.Serializer):
    """The body of a permanent delete; the service reads and checks it, this documents it."""

    verification_phrase = serializers.CharField()


class OrgRemovedJobOrganizationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(help_text="The name when the job was created.")
    exists = serializers.BooleanField()


class OrgRemovedJobSerializer(serializers.ModelSerializer):
    """An organization removed job; expects a row of `org_removed_jobs()`, which annotates
    `organization_exists`."""

    organization = serializers.SerializerMethodField()
    state = serializers.ChoiceField(choices=HookJobState.choices)
    retry_until = serializers.SerializerMethodField()
    allowed_actions = serializers.SerializerMethodField()

    class Meta:
        model = PluginHookJob
        fields = [
            "id",
            "organization",
            "grant_id",
            "state",
            "attempt",
            "first_attempt_at",
            "next_attempt_at",
            "retry_until",
            "finished_at",
            "error",
            "created_at",
            "allowed_actions",
        ]
        read_only_fields = fields

    @extend_schema_field(OrgRemovedJobOrganizationSerializer)
    def get_organization(self, job: PluginHookJob) -> dict:
        return {
            "id": job.organization_id,
            "name": job.organization_name,
            "exists": job.organization_exists,
        }

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_retry_until(self, job: PluginHookJob) -> str | None:
        until = retry_until(job)
        return serializers.DateTimeField().to_representation(until) if until else None

    @extend_schema_field(
        serializers.ListField(
            child=serializers.ChoiceField(choices=[action.value for action in OrgRemovedJobAction])
        )
    )
    def get_allowed_actions(self, job: PluginHookJob) -> list[str]:
        return [action.value for action in allowed_org_removed_job_actions(job, timezone.now())]


class OrgRemovedJobListQuerySerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=["open", "finished", "all"], default="open")
    deleted_organizations = serializers.BooleanField(required=False, allow_null=True, default=None)


class GrantPurgePreviewSerializer(serializers.Serializer):
    """What deleting a grant's data removes; renders a `GrantPurgePreview`."""

    grant = PreviewGrantSerializer()
    plugin = PreviewPluginSerializer(source="grant.plugin")
    organization = PreviewOrganizationSerializer(source="grant.org")
    verification_phrase = serializers.CharField()
    owned_resources = OwnedResourceCountSerializer(many=True)
    flows = PreviewFlowsSerializer(source="*")
    running_sessions = PreviewSessionListSerializer()
    default_models = PreviewDefaultModelSerializer(many=True)
    plugin_data = serializers.ChoiceField(choices=[fate.value for fate in PluginDataFate])


class PurgePluginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    name = serializers.CharField()
    state = serializers.CharField()


class PurgeOrganizationRefSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="organization_id")
    name = serializers.CharField(source="organization_name")


class PurgeOrganizationSerializer(serializers.Serializer):
    grant_id = serializers.IntegerField()
    organization = PurgeOrganizationRefSerializer(source="*")
    state = serializers.CharField()
    owned_resource_count = serializers.IntegerField()


class PurgeOrganizationListSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    items = PurgeOrganizationSerializer(many=True)


class PurgeDatabaseSerializer(serializers.Serializer):
    name = serializers.CharField()
    size_bytes = serializers.IntegerField(allow_null=True)


class PluginPurgePreviewSerializer(serializers.Serializer):
    """What uninstalling or deleting a plugin affects; renders a `PluginPurgePreview`."""

    plugin = PurgePluginSerializer()
    verification_phrase = serializers.CharField()
    data_kept_until = serializers.DateTimeField()
    organizations = PurgeOrganizationListSerializer()
    owned_resources = OwnedResourceCountSerializer(many=True)
    data_removals_open = serializers.IntegerField()
    has_org_removed_hook = serializers.BooleanField()
    database = PurgeDatabaseSerializer(allow_null=True)
    has_backend = serializers.BooleanField()
    has_spa = serializers.BooleanField()
    package_count = serializers.IntegerField()


class PluginPurgeProgressSerializer(serializers.Serializer):
    grants_left = serializers.IntegerField()
    data_removals_waiting = serializers.IntegerField()
    data_removals_failed = serializers.IntegerField()
    node = serializers.ChoiceField(choices=["waiting", "removing", "failed", "not_needed"])
    node_error = serializers.CharField(allow_null=True)
