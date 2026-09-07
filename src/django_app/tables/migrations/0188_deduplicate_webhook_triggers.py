# Hand-written migration — Migration C, part 4 of 4.
# Deduplicates WebhookTrigger rows on (path, provider_type), then enforces the
# new unique_together constraint.
#
# atomic = False is required: the deduplication RunPython cascades deletes through
# the OneToOneField FKs on NgrokWebhookConfig/LocalhostWebhookConfig, which leaves
# deferred FK trigger events pending on WebhookTrigger.  If AlterUniqueTogether
# runs in the same transaction it calls SET CONSTRAINTS IMMEDIATE, which collides
# with those pending events and raises
#   "cannot ALTER TABLE ... because it has pending trigger events".
# Running non-atomically lets the deduplication commit fully (all deferred triggers
# fire and clear) before the schema DDL begins.

from django.db import migrations, models, transaction


def deduplicate_triggers(apps, schema_editor):
    """
    For any (path, provider_type) pair that appears more than once, keep the
    WebhookTrigger with the smallest id and delete the duplicates.
    The OneToOneField on the config models uses ON DELETE CASCADE, so deleting a
    trigger also deletes its linked NgrokWebhookConfig / LocalhostWebhookConfig.
    Wrapped in an explicit savepoint transaction so the deletions commit (and all
    deferred FK trigger events resolve) before control returns to the migration runner.
    """
    WebhookTrigger = apps.get_model("tables", "WebhookTrigger")

    with transaction.atomic():
        seen = {}
        for trigger in WebhookTrigger.objects.order_by("id"):
            key = (trigger.path, trigger.provider_type)
            if key in seen:
                trigger.delete()
            else:
                seen[key] = trigger.pk


class Migration(migrations.Migration):

    atomic = False  # see module docstring above

    dependencies = [
        ("tables", "0187_webhook_trigger_remove_old_fks"),
    ]

    operations = [
        # 1. Deduplicate (commits in its own transaction via atomic=False + explicit block)
        migrations.RunPython(deduplicate_triggers, reverse_code=migrations.RunPython.noop),
        # 2. Set new unique_together on (path, provider_type) — runs in a fresh transaction
        migrations.AlterUniqueTogether(
            name="webhooktrigger",
            unique_together={("path", "provider_type")},
        ),
    ]
