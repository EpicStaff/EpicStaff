from dataclasses import dataclass

from django.db import models

# The first of these a model has, and has filled, names the target.
TARGET_NAME_FIELDS = ("name", "node_name", "custom_name", "collection_name", "path")
# Labels a reader knows a model by, where its verbose_name is an internal word.
TARGET_TYPE_LABELS = {"graph": "flow", "agentdefinition": "agent"}
# The foreign key a record names as the parent of a model the edit tracker gives no owner,
# keyed by the model's `app_label.model_name`. An agent-specific surface belongs to its agent.
TARGET_PARENT_FIELDS = {"agents.surface": "owner_agent"}


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


def target_parent(instance: models.Model) -> models.Model | None:
    """The object a record of `instance` names as its parent, or None when it has none."""
    field_name = TARGET_PARENT_FIELDS.get(instance._meta.label_lower)
    return getattr(instance, field_name) if field_name else None


def target_type(model: type[models.Model]) -> str:
    """The label a user-action record gives rows of `model`, such as "flow"."""
    meta = model._meta
    return TARGET_TYPE_LABELS.get(meta.model_name, str(meta.verbose_name))
