from collections import defaultdict
from dataclasses import dataclass

from django.db import router
from django.db.models import Model
from django.db.models.deletion import Collector

from rbac.governance.delete_resource_names import resource_name


@dataclass
class ModelCount:
    """Row count for one model in a delete cascade."""

    model: str
    count: int


def build_collector(instance: Model) -> Collector:
    """Build and run a Collector against `instance`, without deleting anything."""
    collector = Collector(using=router.db_for_write(instance.__class__, instance=instance))
    collector.collect([instance])
    return collector


def summarize(collector: Collector) -> list[ModelCount]:
    """Every model row an already-collected Collector would remove, largest first."""
    counts: dict[str, int] = defaultdict(int)
    # `data` holds instances Django loads; `fast_deletes` holds querysets it
    # deletes without loading. A model can appear in either, never both, so a
    # report built from `data` alone would silently under-count.
    for model, objects in collector.data.items():
        counts[model._meta.label] += len(objects)
    for queryset in collector.fast_deletes:
        counts[queryset.model._meta.label] += queryset.count()

    by_model = [ModelCount(model=label, count=count) for label, count in counts.items() if count]
    by_model.sort(key=lambda row: (-row.count, row.model))
    return by_model


def build_affected_resources(
    by_model: list[ModelCount], external_counts: dict[str, int] | None = None
) -> dict[str, int]:
    """Fold raw per-model row counts and external artifact counts into the friendly, summed resource-count map the API reports."""
    counts: dict[str, int] = {}
    for row in by_model:
        name = resource_name(row.model)
        if name is None:
            continue
        counts[name] = counts.get(name, 0) + row.count
    for name, count in (external_counts or {}).items():
        if count:
            counts[name] = counts.get(name, 0) + count
    return counts
