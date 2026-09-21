import django.core.validators
from django.db import migrations, models

PATH_MAX_LENGTH = 255


def rename_colliding_paths(apps, schema_editor):
    from loguru import logger

    WebhookTrigger = apps.get_model("tables", "WebhookTrigger")

    triggers = list(WebhookTrigger.objects.order_by("id"))
    # Every path value currently in use -- including ones that will remain
    # untouched (the "winner" of each collision keeps its original path).
    # Any rename target we generate below must avoid this whole set, not
    # just the other paths involved in its own collision, so a computed
    # `-org{id}` suffix can never accidentally collide with some unrelated
    # trigger that already happens to hold that exact literal path.
    taken = {t.path for t in triggers}

    seen = {}
    for trigger in triggers:
        key = trigger.path
        if key not in seen:
            seen[key] = trigger
            continue

        old_path = trigger.path
        suffix = f"-org{trigger.org_id}"
        # Truncate the original path portion (never the suffix) so the
        # final stored value never exceeds the model's max_length=255 --
        # otherwise DB-level truncation could itself create a NEW collision
        # between two truncated paths, or hard-fail the migration outright.
        # The suffix already carries the org id, so two distinct colliding
        # paths truncated to the same prefix still end up unique as long as
        # their org ids differ (which they must -- that's what makes them
        # a cross-org collision in the first place).
        truncated_path = old_path[: PATH_MAX_LENGTH - len(suffix)]
        new_path = f"{truncated_path}{suffix}"
        if new_path in taken:
            # Rare: the org-suffixed name is itself already in use (e.g. by
            # some unrelated trigger that happens to hold that literal
            # path). Disambiguate further with this trigger's own pk, which
            # is guaranteed unique.
            suffix = f"-org{trigger.org_id}-{trigger.pk}"
            truncated_path = old_path[: PATH_MAX_LENGTH - len(suffix)]
            new_path = f"{truncated_path}{suffix}"

        taken.add(new_path)
        trigger.path = new_path
        trigger.save(update_fields=["path"])
        logger.warning(
            f"WebhookTrigger {trigger.pk} (org {trigger.org_id}): renamed "
            f"path '{old_path}' -> '{new_path}' to resolve a cross-org "
            f"path collision ahead of the new global uniqueness constraint "
            f"on path."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0245_role_rbac_role_org_name_ci_uniq"),
    ]

    operations = [
        migrations.RunPython(
            rename_colliding_paths,
            reverse_code=migrations.RunPython.noop,
        ),
        # Clears the org-scoped unique_together introduced by
        # 0216_webhook_trigger_org_path_unique.py (`(org, path,
        # provider_type)`) -- it's being replaced below by a plain
        # `unique=True` on `path` alone, which the ORM can't express as a
        # unique_together member on its own.
        migrations.AlterUniqueTogether(
            name="webhooktrigger",
            unique_together=set(),
        ),
        migrations.AlterField(
            model_name="webhooktrigger",
            name="path",
            field=models.CharField(
                max_length=255,
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        regex="^[a-zA-Z0-9]{1}[a-zA-Z0-9-_]*$",
                        message="Path may only contain letters, numbers, hyphens, and underscores, and must start with a letter or number.",
                    )
                ],
            ),
        ),
    ]
