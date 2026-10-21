"""How many rows of each kind a grant's plugin owns, as the SuperAdmin's dialogs show them."""

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count

from plugins.models import PluginGrant, PluginOwnedResource
from plugins.ownership.existing_owned import existing_owned_resources

# The name each ownable root model is counted under. Every ownable model needs one
# (`ownership_recorder.ownable_models()`); the summary test fails for a model without it.
OWNED_RESOURCE_LABELS = {
    "tables.Graph": "Flows",
    "agents.AgentDefinition": "Agents",
    "agents.Surface": "Surfaces",
    "tables.PythonCodeTool": "Python tools",
    "tables.McpTool": "MCP tools",
    "tables.SourceCollection": "Knowledge collections",
    "tables.KeyValueTable": "Key-value tables",
    "tables.Secret": "Secrets",
    "tables.StorageFile": "Files",
    "tables.WebhookTrigger": "Webhook triggers",
    "tables.RealtimeChannel": "Voice channels",
    "tables.LLMConfig": "LLM configs",
    "tables.EmbeddingConfig": "Embedding configs",
    "tables.RealtimeConfig": "Voice model configs",
    "tables.RealtimeTranscriptionConfig": "Transcription configs",
    "tables.OpenAIRealtimeConfig": "OpenAI voice configs",
    "tables.ElevenLabsRealtimeConfig": "ElevenLabs voice configs",
    "tables.GeminiRealtimeConfig": "Gemini voice configs",
    "tables.LLMModel": "LLM models",
    "tables.EmbeddingModel": "Embedding models",
    "tables.RealtimeModel": "Voice models",
    "tables.RealtimeTranscriptionModel": "Transcription models",
}


def owned_resource_summary(grant: PluginGrant) -> list[dict]:
    """`[{model, label, count}]` of the rows owned under `grant`, sorted by label; one query.

    Counts only resources that still exist (binned ones included), never the ownership rows
    a deleted resource leaves behind.
    """
    counts = (
        existing_owned_resources(PluginOwnedResource.objects.filter(grant=grant))
        .values("content_type_id")
        .annotate(count=Count("pk"))
        .order_by()
        .values_list("content_type_id", "count")
    )
    summary = []
    for content_type_id, count in counts:
        model = ContentType.objects.get_for_id(content_type_id).model_class()._meta.label
        summary.append({"model": model, "label": OWNED_RESOURCE_LABELS[model], "count": count})
    return sorted(summary, key=lambda row: row["label"])
