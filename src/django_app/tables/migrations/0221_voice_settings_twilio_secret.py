# Same secret-FK migration shape as 0220_ngrok_twilio_auth_token_secret.py:
# AddField (nullable FK) -> RunPython backfill (encrypt existing plaintext
# into a new Secret per non-blank value) -> RemoveField (drop the old
# plaintext column).
#
# Unlike 0220 (NgrokWebhookConfig/TwilioChannel, both org-resolvable via a
# parent relation), `VoiceSettings` is a genuine global singleton
# (`DefaultBaseModel`, pk=1, superadmin-only) with no owning organization at
# all — there is no parent to resolve an org id from. `Secret.org` looks
# nullable on the abstract `OrgScopedModel` base, but 0208_secret.py enforces
# `ALTER TABLE tables_secret ALTER COLUMN org_id SET NOT NULL` at the DB
# level, so an `org=None` Secret is not actually a legal row (confirmed by a
# failing `IntegrityError` while writing this migration's test coverage).
# Every `Secret` must have a real owning org.
#
# The backfill therefore anchors on `Organization.is_default=True` — the
# same "stable anchor, rename-proof" fallback org already used elsewhere in
# this codebase for resources with no natural org context (see
# `SuperadminBootstrap._get_or_create_default_org` and
# `import_export/utils.py`'s `Organization.objects.filter(is_default=True)`
# lookup). If no default-flagged org exists yet, fall back to any org; if
# the platform has no organization at all (nothing has been bootstrapped),
# skip the row — same "no resolvable org, skip and log" behavior as 0220's
# `_migrate` helper, since an unconfigured platform cannot have a real
# Twilio credential to migrate in the first place.
#
# This is NOT a schema-only change — see migrate_voice_settings_to_secrets.

from django.db import migrations, models
import django.db.models.deletion
from loguru import logger

from tables.services.secrets import secret_encryption


def migrate_voice_settings_to_secrets(apps, schema_editor):
    Secret = apps.get_model("tables", "Secret")
    VoiceSettings = apps.get_model("tables", "VoiceSettings")
    Organization = apps.get_model("tables", "Organization")

    def _resolve_fallback_org_id():
        org = Organization.objects.filter(is_default=True).first()
        if org is not None:
            return org.pk
        org = Organization.objects.order_by("pk").first()
        return org.pk if org is not None else None

    def _migrate_field(instance, field_name, fk_name, secret_name, org_id):
        raw_value = getattr(instance, field_name)
        if not raw_value:
            return
        secret = Secret(org_id=org_id, name=secret_name, created_by=None)
        secret_encryption.encrypt(text=raw_value).write_to(secret)
        secret.save()
        setattr(instance, fk_name, secret)

    updated = False
    for instance in VoiceSettings.objects.all():
        if not instance.twilio_account_sid and not instance.twilio_auth_token:
            continue

        org_id = _resolve_fallback_org_id()
        if org_id is None:
            logger.warning(
                f"Skipping VoiceSettings pk={instance.pk}: no Organization exists "
                "yet to own the backfilled Secret rows."
            )
            continue

        before = (
            instance.twilio_account_sid_secret_id,
            instance.twilio_auth_token_secret_id,
        )
        _migrate_field(
            instance,
            "twilio_account_sid",
            "twilio_account_sid_secret",
            "voicesettings-twilio-account-sid",
            org_id,
        )
        _migrate_field(
            instance,
            "twilio_auth_token",
            "twilio_auth_token_secret",
            "voicesettings-twilio-auth-token",
            org_id,
        )
        after = (
            instance.twilio_account_sid_secret_id,
            instance.twilio_auth_token_secret_id,
        )
        if after != before:
            instance.save(
                update_fields=["twilio_account_sid_secret", "twilio_auth_token_secret"]
            )
            updated = True

    if not updated:
        logger.info(
            "VoiceSettings secret backfill: no rows with plaintext Twilio "
            "credentials found — nothing to migrate."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0220_ngrok_twilio_auth_token_secret"),
    ]

    operations = [
        migrations.AddField(
            model_name="voicesettings",
            name="twilio_account_sid_secret",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="voice_settings_account_sid_uses",
                to="tables.secret",
            ),
        ),
        migrations.AddField(
            model_name="voicesettings",
            name="twilio_auth_token_secret",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="voice_settings_auth_token_uses",
                to="tables.secret",
            ),
        ),
        migrations.RunPython(
            migrate_voice_settings_to_secrets,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="voicesettings",
            name="twilio_account_sid",
        ),
        migrations.RemoveField(
            model_name="voicesettings",
            name="twilio_auth_token",
        ),
    ]
