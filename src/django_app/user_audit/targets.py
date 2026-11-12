from dataclasses import dataclass

from django.db import models

# The first of these a model has, and has filled, names the target.
TARGET_NAME_FIELDS = ("name", "node_name", "custom_name", "collection_name", "file_name", "path")
# Models named by another field than the first of TARGET_NAME_FIELDS, keyed by
# `app_label.model_name`. A storage entry is known by its full path: one file name repeats
# across folders, and a move or copy records the path too.
TARGET_NAME_FIELD_OVERRIDES = {"tables.storagefile": "path"}
STORAGE_FOLDER_TYPE = "storage folder"
# Labels a reader knows a model by, where its verbose_name is an internal word.
TARGET_TYPE_LABELS = {
    "graph": "flow",
    "graphversion": "flow version",
    "agentdefinition": "agent",
    "llmconfig": "LLM config",
    "llmmodel": "LLM model",
    "mcptool": "MCP tool",
    "pythoncodetool": "custom tool",
    "sourcecollection": "knowledge collection",
    "documentmetadata": "collection file",
    "naiverag": "naive RAG",
    "graphrag": "graph RAG",
    "naiveragdocumentconfig": "file parameters",
    "keyvaluetable": "key-value table",
    "realtimechannel": "voice channel",
    "realtimeagentdefinition": "voice settings",
    "twiliochannel": "Twilio settings",
    "realtimeagentchat": "voice chat",
    "conversationrecording": "call recording",
    "realtimeconfig": "voice config",
    "openairealtimeconfig": "OpenAI voice config",
    "elevenlabsrealtimeconfig": "ElevenLabs voice config",
    "geminirealtimeconfig": "Gemini voice config",
    "realtimetranscriptionconfig": "transcription config",
    "realtimetranscriptionmodel": "transcription model",
    "systemoneconfig": "System One config",
    "defaultmodels": "default LLMs",
    "apikey": "API key",
    "agentnodetask": "agent task",
    "pythonnode": "python code node",
    "keyvaluenode": "key-value node",
    "knowledgenode": "knowledge retriever node",
    "audiotranscriptionnode": "audio to text node",
    "subgraphnode": "subflow node",
    "graphnote": "note",
    # A venv or custom library lives in the sandbox; this side keeps only the binding that
    # stands for it.
    "sandboxvenvbinding": "venv",
    "sandboxcustomlibrarybinding": "custom library",
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
    override = TARGET_NAME_FIELD_OVERRIDES.get(instance._meta.label_lower)
    name_fields = (override,) if override else TARGET_NAME_FIELDS
    name = next(
        (
            str(getattr(instance, field_name))
            for field_name in name_fields
            if getattr(instance, field_name, None)
        ),
        None,
    )
    if name is None and instance._meta.label_lower in TARGET_NAMED_AFTER_PARENT:
        parent = target_parent(instance)
        name = describe(parent).name if parent is not None else None
    return TargetDescription(type=_instance_type(instance), id=str(instance.pk), name=name)


def fields_to_describe(model: type[models.Model]) -> list[str]:
    """The columns `describe` and `target_parent` read from a row of `model`.

    For `QuerySet.only()`, so a row loaded just to be named leaves its other columns, such
    as a flow's metadata JSON, unread. The parent itself is loaded when it is read.
    """
    label = model._meta.label_lower
    override = TARGET_NAME_FIELD_OVERRIDES.get(label)
    wanted = [override] if override else list(TARGET_NAME_FIELDS)
    if label == "tables.storagefile":
        wanted.append("item_type")
    parent_path = TARGET_PARENT_FIELDS.get(label)
    if parent_path is not None:
        wanted.append(parent_path.split("__")[0])
    field_names = {field.name for field in model._meta.concrete_fields}
    return [name for name in wanted if name in field_names]


def describe_reads_the_database(instance: models.Model) -> bool:
    """Whether `describe(instance)` may query: a column it reads was not loaded, or the row
    is named after its parent, which may not be loaded either."""
    if instance._meta.label_lower in TARGET_NAMED_AFTER_PARENT:
        return True
    return not instance.get_deferred_fields().isdisjoint(fields_to_describe(type(instance)))


def _instance_type(instance: models.Model) -> str:
    # One storage model holds both files and folders; a reader tells them apart.
    if instance._meta.label_lower == "tables.storagefile" and instance.item_type == "folder":
        return STORAGE_FOLDER_TYPE
    return target_type(type(instance))


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
