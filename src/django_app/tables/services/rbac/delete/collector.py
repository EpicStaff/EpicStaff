from collections import defaultdict

from django.db import router
from django.db.models.deletion import Collector


def collect_deletion_report(instance) -> dict:
    """Report every row deleting `instance` would remove or null out."""
    collector = Collector(
        using=router.db_for_write(instance.__class__, instance=instance)
    )
    collector.collect([instance])

    counts: dict[str, int] = defaultdict(int)
    # `data` holds instances Django loads; `fast_deletes` holds querysets it
    # deletes without loading. A model can appear in either, never both, so a
    # report built from `data` alone would silently under-count.
    for model, objects in collector.data.items():
        counts[model._meta.label] += len(objects)
    for queryset in collector.fast_deletes:
        counts[queryset.model._meta.label] += queryset.count()

    deleted_labels = {label for label, count in counts.items() if count}

    field_updates = []
    for (field, value), batches in collector.field_updates.items():
        # Django records an update for every SET_NULL edge it crosses, including
        # edges whose holder the same cascade destroys. Those rows are removed,
        # not nulled, so reporting them would contradict `by_model`.
        if field.model._meta.label in deleted_labels:
            continue
        count = sum(len(batch) for batch in batches)
        if count:
            field_updates.append(
                {
                    "model": field.model._meta.label,
                    "field": field.name,
                    "action": "SET_NULL" if value is None else "SET_DEFAULT",
                    "count": count,
                }
            )

    by_model = [
        {"model": label, "count": count} for label, count in counts.items() if count
    ]
    by_model.sort(key=lambda row: (-row["count"], row["model"]))
    field_updates.sort(key=lambda row: (row["model"], row["field"]))

    return {
        "total": sum(row["count"] for row in by_model),
        "by_model": by_model,
        "field_updates": field_updates,
    }
