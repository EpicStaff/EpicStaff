"""Regenerate a sample plugin's resources.json from real models and the real exporter.

    make django-manage CMD="plugin_export_resources --sample chat-bot --output plugins/samples/chat-bot/resources.json"
    make django-manage CMD="plugin_export_resources --sample chat-admin --output ../../plugin-samples/chat-admin/plugin/resources.json"

Everything is built inside a transaction that is rolled back, so the database is
left untouched. The ids inside the output come from the database sequences: after
regenerating, update the refs in the sample's plugin.json to match the ids this
command prints.
"""

import json
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from types import ModuleType

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
    KeyValueNode,
    KeyValueTable,
    LLMConfig,
    LLMModel,
    Provider,
    PythonCode,
    PythonNode,
    StartNode,
    TaskNode,
)

from plugins.samples.chat_admin_code import append_turn, format_history

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

CHAT_ADMIN_AGENT_INSTRUCTIONS = (
    "You are a friendly, helpful support assistant. Answer clearly and concisely, in the "
    "language the user writes in, and use the earlier conversation for context. If you "
    "are not sure about something, say so instead of guessing. Keep answers short unless "
    "the user asks for detail."
)
CHAT_ADMIN_TASK_INSTRUCTIONS = (
    "Conversation so far:\n{history}\n\n"
    "New message from the user:\n{question}\n\n"
    "Reply to the new message helpfully and concisely."
)
# Where the flow keeps conversations: one entry per conversation id.
CONVERSATION_ENTRY = {"key": "{variables.conversation_id}"}


class Command(BaseCommand):
    help = "Build a sample plugin's flow in a rolled-back transaction and write its export."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sample", required=True, choices=sorted(SAMPLE_BUILDERS), help="Which sample."
        )
        parser.add_argument("--output", required=True, help="Where to write resources.json.")

    def handle(self, *args, **options):
        with transaction.atomic():
            data, refs = SAMPLE_BUILDERS[options["sample"]]()
            transaction.set_rollback(True)

        output = Path(options["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(f"Wrote {output}")
        for name, ref in refs.items():
            self.stdout.write(f"  {name}: {ref}")


def build_chat_bot_resources() -> tuple[dict, dict[str, int]]:
    """Create the chat-bot sample's rows in a scratch org and export them as one Flow bundle.

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


def build_chat_admin_resources() -> tuple[dict, dict[str, int]]:
    """Create the chat-admin sample's rows in a scratch org and export them as one Flow bundle.

    The flow answers one chat message and keeps the whole conversation in the
    `conversations` table, so the plugin's page only ever sends
    `{conversation_id, question}` and reads transcripts back from the table:

        Start -> Load conversation (read) -> Format history (Python) -> Answer (task)
              -> Append turn (Python) -> Save conversation (write) -> End

    Returns the export plus the ids plugin.json refers to.
    """
    org = Organization.objects.create(name="plugin-sample-export")
    openai, _ = Provider.objects.get_or_create(name="openai")
    llm_model = _catalog_model(LLMModel, "gpt-4o-mini", llm_provider=openai)
    llm_config = LLMConfig.objects.create(
        org=org, custom_name="Chat Admin GPT-4o mini", model=llm_model, temperature=0.3
    )
    agent = AgentDefinition.objects.create(
        organization=org,
        name="Chat Admin Agent",
        description="Answers chat messages as a general support assistant.",
        instructions=CHAT_ADMIN_AGENT_INSTRUCTIONS,
        llm_config=llm_config,
    )
    table = KeyValueTable.objects.create(
        org=org, name="conversations", description="One entry per chat conversation."
    )

    graph = Graph.objects.create(
        org=org,
        name="Chat Admin",
        description="Answers a chat message and keeps the conversation in a key-value table.",
        metadata={},
    )
    nodes = [
        StartNode.objects.create(
            graph=graph,
            variables={"variables": {"conversation_id": "", "question": ""}},
            metadata=_position(0),
        ),
        # A conversation not stored yet reads as None.
        KeyValueNode.objects.create(
            graph=graph,
            node_name="Load conversation",
            key_value_table=table,
            mode=KeyValueNode.Mode.READ,
            entries=[{**CONVERSATION_ENTRY, "value": "variables.conversation"}],
            metadata=_position(1),
        ),
        _python_node(
            graph,
            "Format history",
            format_history,
            input_map={"conversation": "variables.conversation"},
            output_variable_path="variables.history",
            position=2,
        ),
        TaskNode.objects.create(
            graph=graph,
            node_name="Answer",
            agent_definition=agent,
            instructions=CHAT_ADMIN_TASK_INSTRUCTIONS,
            input_map={"question": "variables.question", "history": "variables.history"},
            output_variable_path="variables.answer",
            metadata=_position(3),
        ),
        _python_node(
            graph,
            "Append turn",
            append_turn,
            input_map={
                "conversation_id": "variables.conversation_id",
                "conversation": "variables.conversation",
                "question": "variables.question",
                "answer": "variables.answer",
            },
            output_variable_path="variables.record",
            position=4,
        ),
        KeyValueNode.objects.create(
            graph=graph,
            node_name="Save conversation",
            key_value_table=table,
            mode=KeyValueNode.Mode.WRITE,
            entries=[{**CONVERSATION_ENTRY, "value": "variables.record"}],
            metadata=_position(5),
        ),
        EndNode.objects.create(
            graph=graph,
            output_map={
                "answer": "variables.answer",
                "conversation_id": "variables.conversation_id",
            },
            metadata=_position(6),
        ),
    ]
    for source, target in pairwise(nodes):
        Edge.objects.create(graph=graph, start_node_id=source.id, end_node_id=target.id)

    data = ExportService(entity_registry).export_entities(
        EntityType.GRAPH, [graph.id], org_id=org.id
    )
    refs = {"Flow": graph.id, "LLMConfig": llm_config.id, "KeyValueTable": table.id}
    return data, refs


SAMPLE_BUILDERS: dict[str, Callable[[], tuple[dict, dict[str, int]]]] = {
    "chat-bot": build_chat_bot_resources,
    "chat-admin": build_chat_admin_resources,
}


def _python_node(
    graph: Graph,
    name: str,
    source: ModuleType,
    *,
    input_map: dict,
    output_variable_path: str,
    position: int,
) -> PythonNode:
    code = PythonCode.objects.create(
        code=Path(source.__file__).read_text(encoding="utf-8"), entrypoint="main"
    )
    return PythonNode.objects.create(
        graph=graph,
        node_name=name,
        python_code=code,
        input_map=input_map,
        output_variable_path=output_variable_path,
        metadata=_position(position),
    )


def _position(column: int) -> dict:
    return {"position": {"x": column * 320, "y": 0}}


def _catalog_model(model_class, name: str, **provider):
    """The shared catalog row the export points at, created only if this database lacks it."""
    existing = model_class.objects.filter(name=name, is_custom=False, **provider).first()
    return existing or model_class.objects.create(name=name, is_custom=False, **provider)
