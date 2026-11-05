from dataclasses import dataclass

from django.db import models

# The first of these a model has, and has filled, names the target.
TARGET_NAME_FIELDS = ("name", "node_name", "custom_name", "collection_name", "file_name", "path")
# Labels a reader knows a model by, where its verbose_name is an internal word.
TARGET_TYPE_LABELS = {
    "graph": "flow",
    "graphversion": "flow version",
    "agentdefinition": "agent",
    "llmconfig": "LLM config",
    "llmmodel": "LLM model",
    "openairealtimeconfig": "OpenAI realtime config",
    "elevenlabsrealtimeconfig": "ElevenLabs realtime config",
    "documentmetadata": "document",
    "realtimeagentdefinition": "voice settings",
    "twiliochannel": "Twilio settings",
    "realtimeagentchat": "voice chat",
    "conversationrecording": "call recording",
    "agentnodetask": "agent task",
    "naiverag": "naive RAG",
    "graphrag": "graph RAG",
    # A venv lives in the sandbox; this side keeps only the binding that stands for it.
    "sandboxvenvbinding": "venv",
}
# The foreign key a record names as the parent of a model the edit tracker gives no owner,
# keyed by the model's `app_label.model_name`. An agent-specific surface belongs to its agent,
# a flow version and a session to their flow, a document to its collection. A one-to-one
# parent also names a child that has no name of its own (see `describe`).
TARGET_PARENT_FIELDS = {
    "agents.surface": "owner_agent",
    "tables.graphversion": "graph",
    "tables.session": "graph",
    "tables.documentmetadata": "source_collection",
    "tables.agentnodetask": "agent_node",
    "tables.realtimeagentdefinition": "agent_definition",
    "tables.twiliochannel": "channel",
    "tables.realtimeagentchat": "rt_agent_definition",
    "tables.conversationrecording": "rt_agent_chat",
}


@dataclass(frozen=True)
class TargetDescription:
    type: str
    id: str
    name: str | None


def describe(instance: models.Model) -> TargetDescription:
    """Describe a saved model instance the way a user-action record shows it.

    A row with no name of its own that belongs one-to-one to its parent (an agent's voice
    settings) takes the parent's name.
    """
    name = next(
        (
            str(getattr(instance, field_name))
            for field_name in TARGET_NAME_FIELDS
            if getattr(instance, field_name, None)
        ),
        None,
    )
    if name is None and _has_one_to_one_parent(instance):
        parent = target_parent(instance)
        name = describe(parent).name if parent is not None else None
    return TargetDescription(type=target_type(type(instance)), id=str(instance.pk), name=name)


def _has_one_to_one_parent(instance: models.Model) -> bool:
    field_name = TARGET_PARENT_FIELDS.get(instance._meta.label_lower)
    return field_name is not None and instance._meta.get_field(field_name).one_to_one


def describe_user(user) -> TargetDescription:
    """Describe a user by email, the name every reader of the record knows them by."""
    return TargetDescription(type="user", id=str(user.pk), name=user.email)


def target_parent(instance: models.Model) -> models.Model | None:
    """The object a record of `instance` names as its parent, or None when it has none."""
    field_name = TARGET_PARENT_FIELDS.get(instance._meta.label_lower)
    return getattr(instance, field_name) if field_name else None


def target_type(model: type[models.Model]) -> str:
    """The label a user-action record gives rows of `model`, such as "flow"."""
    meta = model._meta
    return TARGET_TYPE_LABELS.get(meta.model_name, str(meta.verbose_name))
