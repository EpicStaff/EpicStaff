import re

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# Frozen copies, as a migration must not import code that may change later:
# Permission.USE, ResourceType.SECRETS, and SecretResolver's header marker.
_USE = 64
_SECRETS = "secrets"
_SECRET_MARKER = re.compile(r"epicstaff_secret\(\s*([^)]+?)\s*\)")


def _has_marker(headers) -> bool:
    if not isinstance(headers, dict):
        return False
    return any(isinstance(value, str) and _SECRET_MARKER.search(value) for value in headers.values())


def _is_custom_model(model) -> bool:
    # The catalog is a built-in row with no org; anything else is its own destination.
    return model is not None and (model.is_custom or model.org_id is not None)


def _llm_config_needs_approval(config) -> bool:
    custom = _is_custom_model(config.model) or bool(config.base_url)
    return custom and (config.api_key_secret_id is not None or _has_marker(config.extra_headers))


def _embedding_config_needs_approval(config) -> bool:
    return _is_custom_model(config.model) and config.api_key_secret_id is not None


def _openai_realtime_config_needs_approval(config) -> bool:
    carries = (
        config.api_key_secret_id is not None or config.transcription_api_key_secret_id is not None
    )
    return bool(config.base_url) and carries


def backfill_secret_binding_approvers(apps, schema_editor=None):
    """Approve the secret binding of each config that sends a secret somewhere custom.

    The approver is the row's last editor, or its creator when no editor is recorded
    (no last edit, or one whose editor is NULL), and only if that user holds
    secrets:USE in the row's org today; otherwise the row
    stays NULL and its secret stops being delivered until an admin re-saves it. USE is
    read the way PermissionResolver reads it -- superadmin, or an active membership whose
    role grants USE on secrets -- from the historical tables, since the resolver itself
    imports live models.
    """
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    OrganizationUser = apps.get_model("rbac", "OrganizationUser")
    RolePermission = apps.get_model("rbac", "RolePermission")
    ResourceLastEdit = apps.get_model("rbac", "ResourceLastEdit")
    ContentType = apps.get_model("contenttypes", "ContentType")

    superadmin_ids = set(User.objects.filter(is_superadmin=True).values_list("pk", flat=True))
    use_role_ids = {
        role_id
        for role_id, permissions in RolePermission.objects.filter(
            resource_type=_SECRETS
        ).values_list("role_id", "permissions")
        if permissions & _USE
    }
    use_memberships = set(
        OrganizationUser.objects.filter(role_id__in=use_role_ids, org__is_active=True).values_list(
            "user_id", "org_id"
        )
    )

    def holds_use(user_id, org_id) -> bool:
        return user_id is not None and (
            user_id in superadmin_ids or (user_id, org_id) in use_memberships
        )

    for model_name, needs_approval in (
        ("LLMConfig", _llm_config_needs_approval),
        ("EmbeddingConfig", _embedding_config_needs_approval),
        ("OpenAIRealtimeConfig", _openai_realtime_config_needs_approval),
    ):
        Config = apps.get_model("tables", model_name)
        content_type = ContentType.objects.filter(
            app_label="tables", model=model_name.lower()
        ).first()
        last_editors = (
            dict(
                ResourceLastEdit.objects.filter(content_type=content_type).values_list(
                    "object_id", "edited_by_id"
                )
            )
            if content_type is not None
            else {}
        )
        rows = Config.objects.all()
        if model_name != "OpenAIRealtimeConfig":
            rows = rows.select_related("model")
        for config in rows.iterator():
            if not needs_approval(config):
                continue
            candidate_id = last_editors.get(config.pk) or config.created_by_id
            if holds_use(candidate_id, config.org_id):
                Config.objects.filter(pk=config.pk).update(secret_binding_approved_by_id=candidate_id)


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0272_merge_20261016_1000"),
        ("rbac", "0007_chats_resource_type"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="embeddingconfig",
            name="secret_binding_approved_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="llmconfig",
            name="secret_binding_approved_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="openairealtimeconfig",
            name="secret_binding_approved_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_secret_binding_approvers, migrations.RunPython.noop),
    ]
