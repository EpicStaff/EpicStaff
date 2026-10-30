from dataclasses import dataclass

from django.db import models

# The first of these a model has, and has filled, names the target.
TARGET_NAME_FIELDS = ("name", "node_name", "custom_name", "collection_name", "path")
# Labels a reader knows a model by, where its verbose_name is an internal word.
TARGET_TYPE_LABELS = {"graph": "flow"}


@dataclass(frozen=True)
class TargetDescription:
    type: str
    id: str
    name: str | None


def describe(instance: models.Model) -> TargetDescription:
    """Describe a saved model instance the way a user-action record shows it."""
    name = next(
        (
            str(getattr(instance, field_name))
            for field_name in TARGET_NAME_FIELDS
            if getattr(instance, field_name, None)
        ),
        None,
    )
    return TargetDescription(type=target_type(type(instance)), id=str(instance.pk), name=name)


def target_type(model: type[models.Model]) -> str:
    """The label a user-action record gives rows of `model`, such as "flow"."""
    meta = model._meta
    return TARGET_TYPE_LABELS.get(meta.model_name, str(meta.verbose_name))
