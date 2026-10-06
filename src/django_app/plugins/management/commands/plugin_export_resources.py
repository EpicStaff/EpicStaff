"""Regenerate samples/chat-bot/resources.json from real models and the real exporter.

    make django-manage CMD="plugin_export_resources --output plugins/samples/chat-bot/resources.json"

Everything is built inside a transaction that is rolled back, so the database is
left untouched. The ids inside the output come from the database sequences: after
regenerating, update the refs in samples/chat-bot/plugin.json to match the ids
this command prints.
"""

import json
from pathlib import Path

from agents.models import AgentDefinition, Surface
from django.core.management.base import BaseCommand
from django.db import transaction
from rbac.models import Organization
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import (
    Edge,
    EmbeddingConfig,
    EmbeddingModel,
    EndNode,
    Graph,
    LLMConfig,
    LLMModel,
    Provider,
    StartNode,
    TaskNode,
)

AGENT_INSTRUCTIONS = (
    "You are the support assistant for Acme Notes. Answer only from the Acme Notes "
    "knowledge you can search and the files you can read. Follow the tone guide in "
    "your storage files. If the knowledge does not cover a question, say so plainly "
    "and suggest contacting support@acme-notes.example."
)
TASK_INSTRUCTIONS = (
    "Conversation so far:\n{history}\n\n"
    "Customer question:\n{question}\n\n"
    "Search the Acme Notes knowledge before answering, then reply in a few short "
    "paragraphs."
)


class Command(BaseCommand):
    help = "Build the chat-bot sample flow in a rolled-back transaction and write its export."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True, help="Where to write resources.json.")

    def handle(self, *args, **options):
        with transaction.atomic():
            data, refs = build_chat_bot_resources()
            transaction.set_rollback(True)

        Path(options["output"]).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(f"Wrote {options['output']}")
        for name, ref in refs.items():
            self.stdout.write(f"  {name}: {ref}")


def build_chat_bot_resources() -> tuple[dict, dict[str, int]]:
    """Create the sample's rows in a scratch org and export them as one Flow bundle.

    Returns the export plus the ids plugin.json refers to.
    """
    org = Organization.objects.create(name="plugin-sample-export")
    openai, _ = Provider.objects.get_or_create(name="openai")
    llm_model = _catalog_model(LLMModel, "gpt-4o-mini", llm_provider=openai)
    embedding_model = _catalog_model(
        EmbeddingModel, "text-embedding-3-small", embedding_provider=openai
    )

    llm_config = LLMConfig.objects.create(
        org=org, custom_name="Chat Bot GPT-4o mini", model=llm_model, temperature=0.3
    )
    embedding_config = EmbeddingConfig.objects.create(
        org=org,
        custom_name="Chat Bot embeddings",
        model=embedding_model,
        task_type="retrieval_document",
    )
    agent = AgentDefinition.objects.create(
        organization=org,
        name="Chat Bot Agent",
        description="Answers customer questions about Acme Notes.",
        instructions=AGENT_INSTRUCTIONS,
        llm_config=llm_config,
    )
    surface = Surface.objects.create(
        organization=org,
        name="Chat Bot Agent knowledge",
        instructions="Use the Acme Notes knowledge and the tone guide when you answer.",
        owner_agent=agent,
    )

    graph = Graph.objects.create(
        org=org,
        name="Chat Bot",
        description="Answers a customer question using the Acme Notes knowledge.",
        metadata={},
    )
    start = StartNode.objects.create(
        graph=graph,
        variables={"variables": {"question": "", "history": ""}},
        metadata={"position": {"x": 0, "y": 0}},
    )
    task = TaskNode.objects.create(
        graph=graph,
        node_name="Answer question",
        agent_definition=agent,
        instructions=TASK_INSTRUCTIONS,
        input_map={"question": "variables.question", "history": "variables.history"},
        output_variable_path="variables.answer",
        metadata={"position": {"x": 420, "y": 0}},
    )
    end = EndNode.objects.create(
        graph=graph,
        output_map={"answer": "variables.answer"},
        metadata={"position": {"x": 840, "y": 0}},
    )
    Edge.objects.create(graph=graph, start_node_id=start.id, end_node_id=task.id)
    Edge.objects.create(graph=graph, start_node_id=task.id, end_node_id=end.id)

    exporter = ExportService(entity_registry)
    data = exporter.export_entities(EntityType.GRAPH, [graph.id], org_id=org.id)
    # Nothing in the flow references the embedding config (the knowledge collection
    # that uses it is created from plugin.json), so it is exported separately.
    embedding_export = exporter.export_entities(
        EntityType.EMBEDDING_CONFIG, [embedding_config.id], org_id=org.id
    )
    for entity_type in (EntityType.EMBEDDING_MODEL, EntityType.EMBEDDING_CONFIG):
        data[entity_type] = embedding_export[entity_type]

    refs = {
        "Flow": graph.id,
        "Surface": surface.id,
        "LLMConfig": llm_config.id,
        "EmbeddingConfig": embedding_config.id,
    }
    return data, refs


def _catalog_model(model_class, name: str, **provider):
    """The shared catalog row the export points at, created only if this database lacks it."""
    existing = model_class.objects.filter(name=name, is_custom=False, **provider).first()
    return existing or model_class.objects.create(name=name, is_custom=False, **provider)
