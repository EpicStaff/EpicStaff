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
    "naiveragdocumentconfig": "document chunking settings",
    # A venv lives in the sandbox; this side keeps only the binding that stands for it.
    "sandboxvenvbinding": "venv",
}
# The relation a record names as the parent of a model the edit tracker gives no owner,
# keyed by the model's `app_label.model_name`; `__` follows several relations. An
# agent-specific surface belongs to its agent, a flow version and a session to their flow, a
# document and a RAG to their collection.
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
    "tables.naiverag": "base_rag_type__source_collection",
    "tables.graphrag": "base_rag_type__source_collection",
    "tables.naiveragdocumentconfig": "document",
}
# Models with no name of their own whose rows a reader knows by their parent's: an agent's
# voice settings, a channel's Twilio settings, a collection's RAG (one of each type), a
# document's chunking settings in that RAG.
TARGET_NAMED_AFTER_PARENT = frozenset(
    {
        "tables.realtimeagentdefinition",
        "tables.twiliochannel",
        "tables.naiverag",
        "tables.graphrag",
        "tables.naiveragdocumentconfig",
    }
)


@dataclass(frozen=True)
class TargetDescription:
    type: str
    id: str
    name: str | None


def describe(instance: models.Model) -> TargetDescription:
    """Describe a saved model instance the way a user-action record shows it.

    A row of a model in `TARGET_NAMED_AFTER_PARENT` is named after its parent.
    """
    name = next(
        (
            str(getattr(instance, field_name))
            for field_name in TARGET_NAME_FIELDS
            if getattr(instance, field_name, None)
        ),
        None,
    )
    if name is None and instance._meta.label_lower in TARGET_NAMED_AFTER_PARENT:
        parent = target_parent(instance)
        name = describe(parent).name if parent is not None else None
    return TargetDescription(type=target_type(type(instance)), id=str(instance.pk), name=name)


def describe_user(user) -> TargetDescription:
    """Describe a user by email, the name every reader of the record knows them by."""
    return TargetDescription(type="user", id=str(user.pk), name=user.email)


def target_parent(instance: models.Model) -> models.Model | None:
    """The object a record of `instance` names as its parent, or None when it has none."""
    path = TARGET_PARENT_FIELDS.get(instance._meta.label_lower)
    if path is None:
        return None
    parent = instance
    for field_name in path.split("__"):
        parent = getattr(parent, field_name)
        if parent is None:
            return None
    return parent


def target_type(model: type[models.Model]) -> str:
    """The label a user-action record gives rows of `model`, such as "flow"."""
    meta = model._meta
    return TARGET_TYPE_LABELS.get(meta.model_name, str(meta.verbose_name))
