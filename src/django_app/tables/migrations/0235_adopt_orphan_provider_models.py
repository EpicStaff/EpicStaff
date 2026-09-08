"""Data fixups that must land before 0236 adds the per-org uniqueness constraints.

Kept in a separate migration from the DDL on purpose: Postgres refuses to
ALTER TABLE a table that has pending trigger events from DML earlier in the same
transaction, and `collapse_same_org_realtime_duplicates` writes to the very
tables 0236 then constrains.
"""

from django.db import migrations
from django.db.models import Count
from loguru import logger

_ADOPTION_TARGETS = (
    ("tables.LLMModel", "tables.LLMConfig", "model"),
    ("tables.EmbeddingModel", "tables.EmbeddingConfig", "model"),
)

_REALTIME_TARGETS = (
    ("tables.RealtimeModel", "tables.RealtimeConfig", "realtime_model"),
    (
        "tables.RealtimeTranscriptionModel",
        "tables.RealtimeTranscriptionConfig",
        "realtime_transcription_model",
    ),
)

_DUPLICATE_CHECK_TARGETS = (
    ("tables.LLMModel", "llm_provider_id"),
    ("tables.EmbeddingModel", "embedding_provider_id"),
)


def adopt_orphans(apps, *, model_label: str, config_label: str, config_fk: str) -> None:
    """Adopts quickstart-orphaned provider model rows into the single org that references them."""
    model_cls = apps.get_model(model_label)
    config_cls = apps.get_model(config_label)

    # predefined=False is what keeps genuine catalog rows out: upload_models
    # always sets predefined=True, so only quickstart's output matches.
    orphans = model_cls.objects.filter(
        org__isnull=True, is_custom=False, predefined=False
    )
    for orphan in orphans:
        org_ids = set(
            config_cls.objects.filter(**{config_fk: orphan})
            .exclude(org__isnull=True)
            .values_list("org_id", flat=True)
        )
        if len(org_ids) != 1:
            # Zero → nothing to infer ownership from. More than one → adopting it
            # into either org would break the other, and re-pointing another
            # org's FK is not a migration's decision. Leave it shared.
            logger.info(
                "Leaving orphan {} row id={} shared: {} referencing orgs",
                model_label,
                orphan.pk,
                len(org_ids),
            )
            continue
        orphan.org_id = org_ids.pop()
        orphan.is_custom = True
        orphan.save(update_fields=["org", "is_custom"])
        logger.info(
            "Adopted orphan {} row id={} into org {}",
            model_label,
            orphan.pk,
            orphan.org_id,
        )


def collapse_duplicates(
    apps, *, model_label: str, config_label: str, config_fk: str
) -> None:
    """Collapses same-org duplicate rows, which the realtime registries had no constraint to prevent."""
    model_cls = apps.get_model(model_label)
    config_cls = apps.get_model(config_label)

    groups = (
        model_cls.objects.values("org_id", "name", "provider_id")
        .annotate(n=Count("id"))
        .filter(n__gt=1)
    )
    for group in groups:
        rows = list(
            model_cls.objects.filter(
                org_id=group["org_id"],
                name=group["name"],
                provider_id=group["provider_id"],
            ).order_by("pk")
        )
        keeper, extras = rows[0], rows[1:]
        # Re-point BEFORE deleting: both config FKs are CASCADE, so deleting
        # first would destroy that org's live realtime configs.
        config_cls.objects.filter(
            **{f"{config_fk}__in": [e.pk for e in extras]}
        ).update(**{config_fk: keeper})
        model_cls.objects.filter(pk__in=[e.pk for e in extras]).delete()
        logger.info(
            "Collapsed {} duplicates of ({}, {}) in org {} onto id={}",
            len(extras),
            model_label,
            group["name"],
            group["org_id"],
            keeper.pk,
        )


def forwards(apps, schema_editor):
    for model_label, config_label, config_fk in _ADOPTION_TARGETS:
        adopt_orphans(
            apps,
            model_label=model_label,
            config_label=config_label,
            config_fk=config_fk,
        )
    for model_label, config_label, config_fk in _REALTIME_TARGETS:
        collapse_duplicates(
            apps,
            model_label=model_label,
            config_label=config_label,
            config_fk=config_fk,
        )
    _assert_no_remaining_duplicates(apps)


def _assert_no_remaining_duplicates(apps) -> None:
    """Fails loudly if any row would still violate the constraints 0236 is about to add."""
    for label, provider_field in _DUPLICATE_CHECK_TARGETS:
        model_cls = apps.get_model(label)
        dupes = list(
            model_cls.objects.values("org_id", "name", provider_field)
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        if dupes:
            raise RuntimeError(
                f"{label} has rows violating the new per-org uniqueness: {dupes}"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("tables", "0234_merge_knowledge_node_and_agent_node_migrations"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
