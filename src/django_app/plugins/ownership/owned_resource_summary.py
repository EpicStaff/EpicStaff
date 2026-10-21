"""How many rows of each kind a grant's plugin owns, as the SuperAdmin's dialogs show them."""

from collections import defaultdict

from django.contrib.contenttypes.models import ContentType

from plugins.models import PluginGrant, PluginOwnedResource
from plugins.ownership.existing_owned import existing_owned_counts, owned_resource_counts_by_grant

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
    """`[{model, label, count}]` of the rows owned under `grant`, sorted by label.

    Counts only resources that still exist (binned ones included), never the ownership rows
    a deleted resource leaves behind: one query for the kinds present, then one per kind. A
    kind without a label is left out.
    """
    by_content_type: dict[int, int] = defaultdict(int)
    for (_, content_type_id), count in existing_owned_counts(
        PluginOwnedResource.objects.filter(grant=grant)
    ).items():
        by_content_type[content_type_id] += count
    summary = []
    for content_type_id, count in by_content_type.items():
        model = ContentType.objects.get_for_id(content_type_id).model_class()._meta.label
        label = OWNED_RESOURCE_LABELS.get(model)
        if label is not None:
            summary.append({"model": model, "label": label, "count": count})
    return sorted(summary, key=lambda row: row["label"])


def with_owned_resource_counts(grants: list[PluginGrant]) -> list[PluginGrant]:
    """Set `owned_resource_count` on each of `grants`, a page of the SuperAdmin's grant list.

    Counted for the page only, per kind of resource, after pagination: one query for the kinds
    present, then one per kind.
    """
    counts = owned_resource_counts_by_grant(grant.pk for grant in grants)
    for grant in grants:
        grant.owned_resource_count = counts.get(grant.pk, 0)
    return grants
