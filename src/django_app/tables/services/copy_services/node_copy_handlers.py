from typing import Callable

from tables.constants.variables_constants import (
    DOMAIN_ORGANIZATION_KEY,
    DOMAIN_USER_KEY,
)
from tables.import_export.enums import NodeType
from tables.models import Graph
from tables.models.graph_models import (
    AudioTranscriptionNode,
    ConditionGroup,
    Condition,
    CrewNode,
    DecisionTableNode,
    EndNode,
    FileExtractorNode,
    GraphOrganization,
    GraphOrganizationUser,
    LLMNode,
    GraphNote,
    PythonNode,
    StartNode,
    SubGraphNode,
    TelegramTriggerNode,
    TelegramTriggerNodeField,
    CodeAgentNode,
    WebhookTriggerNode,
)
from tables.services.copy_services.helpers import copy_python_code, get_base_node_fields
from tables.services.persistent_variables_service import PersistentVariablesService


def copy_start_node(graph: Graph, node: StartNode) -> StartNode:
    new_node = StartNode.objects.create(
        graph=graph,
        variables=node.variables,
        metadata=node.metadata,
    )

    source_org = GraphOrganization.objects.filter(graph=node.graph).first()
    if source_org:
        service = PersistentVariablesService()
        GraphOrganization.objects.create(
            graph=graph,
            organization=source_org.organization,
            persistent_variables=service.extract(
                node.variables, DOMAIN_ORGANIZATION_KEY
            ),
            user_variables=service.extract(node.variables, DOMAIN_USER_KEY),
        )
        for org_user in GraphOrganizationUser.objects.filter(graph=node.graph):
            GraphOrganizationUser.objects.create(
                graph=graph,
                user=org_user.user,
                persistent_variables=service.extract(node.variables, DOMAIN_USER_KEY),
            )

    return new_node


def copy_end_node(graph: Graph, node: EndNode) -> EndNode:
    return EndNode.objects.create(
        graph=graph,
        output_map=node.output_map,
        metadata=node.metadata,
    )


def copy_graph_note(graph: Graph, node: GraphNote) -> GraphNote:
    return GraphNote.objects.create(
        graph=graph, content=node.content, metadata=node.metadata
    )


def copy_file_extractor_node(
    graph: Graph, node: FileExtractorNode
) -> FileExtractorNode:
    return FileExtractorNode.objects.create(
        graph=graph,
        **get_base_node_fields(node),
    )


def copy_audio_transcription_node(
    graph: Graph, node: AudioTranscriptionNode
) -> AudioTranscriptionNode:
    return AudioTranscriptionNode.objects.create(
        graph=graph,
        **get_base_node_fields(node),
    )


def copy_llm_node(graph: Graph, node: LLMNode) -> LLMNode:
    return LLMNode.objects.create(
        graph=graph,
        llm_config=node.llm_config,
        **get_base_node_fields(node),
    )


def copy_crew_node(graph: Graph, node: CrewNode) -> CrewNode:
    return CrewNode.objects.create(
        graph=graph,
        crew=node.crew,
        **get_base_node_fields(node),
    )


def copy_subgraph_node(graph: Graph, node: SubGraphNode) -> SubGraphNode:
    return SubGraphNode.objects.create(
        graph=graph,
        subgraph=node.subgraph,
        **get_base_node_fields(node),
    )


def copy_python_node(graph: Graph, node: PythonNode) -> PythonNode:
    new_code = copy_python_code(node.python_code)
    return PythonNode.objects.create(
        graph=graph,
        python_code=new_code,
        **get_base_node_fields(node),
    )


def copy_webhook_trigger_node(
    graph: Graph, node: WebhookTriggerNode
) -> WebhookTriggerNode:
    new_code = copy_python_code(node.python_code)
    return WebhookTriggerNode.objects.create(
        graph=graph,
        node_name=node.node_name,
        webhook_trigger=node.webhook_trigger,
        python_code=new_code,
        metadata=node.metadata,
    )


def copy_telegram_trigger_node(
    graph: Graph, node: TelegramTriggerNode
) -> TelegramTriggerNode:
    new_node = TelegramTriggerNode.objects.create(
        graph=graph,
        node_name=node.node_name,
        telegram_bot_api_key=node.telegram_bot_api_key,
        webhook_trigger=node.webhook_trigger,
        metadata=node.metadata,
    )
    for field in node.fields.all():
        TelegramTriggerNodeField.objects.create(
            telegram_trigger_node=new_node,
            parent=field.parent,
            field_name=field.field_name,
            variable_path=field.variable_path,
        )
    return new_node


def copy_code_agent_node(graph: Graph, node: CodeAgentNode) -> CodeAgentNode:
    return CodeAgentNode.objects.create(
        graph=graph,
        llm_config=node.llm_config,
        agent_mode=node.agent_mode,
        session_id=node.session_id,
        system_prompt=node.system_prompt,
        stream_handler_code=node.stream_handler_code,
        libraries=node.libraries,
        polling_interval_ms=node.polling_interval_ms,
        silence_indicator_s=node.silence_indicator_s,
        indicator_repeat_s=node.indicator_repeat_s,
        chunk_timeout_s=node.chunk_timeout_s,
        inactivity_timeout_s=node.inactivity_timeout_s,
        max_wait_s=node.max_wait_s,
        stream_config=node.stream_config,
        output_schema=node.output_schema,
        **get_base_node_fields(node),
    )


def copy_decision_table_node(
    graph: Graph, node: DecisionTableNode
) -> DecisionTableNode:
    new_node = DecisionTableNode.objects.create(
        graph=graph,
        node_name=node.node_name,
        default_next_node_id=node.default_next_node_id,
        next_error_node_id=node.next_error_node_id,
        metadata=node.metadata,
    )
    for group in node.condition_groups.all():
        new_group = ConditionGroup.objects.create(
            decision_table_node=new_node,
            group_name=group.group_name,
            group_type=group.group_type,
            order=group.order,
            expression=group.expression,
            manipulation=group.manipulation,
            next_node_id=group.next_node_id,
        )
        for condition in group.conditions.all():
            Condition.objects.create(
                condition_group=new_group,
                condition_name=condition.condition_name,
                order=condition.order,
                condition=condition.condition,
            )
    return new_node


# Maps each NodeType to (relation_name, handler_function).
# relation_name is the Graph reverse accessor used to iterate existing nodes.
# To add a new node type: write a copy_<name> function above and add one entry here.
NODE_COPY_HANDLERS: dict[NodeType, tuple[str, Callable]] = {
    NodeType.START_NODE: ("start_node_list", copy_start_node),
    NodeType.END_NODE: ("end_node", copy_end_node),
    NodeType.NOTE_NODE: ("graph_note_list", copy_graph_note),
    NodeType.FILE_EXTRACTOR_NODE: (
        "file_extractor_node_list",
        copy_file_extractor_node,
    ),
    NodeType.AUDIO_TRANSCRIPTION_NODE: (
        "audio_transcription_node_list",
        copy_audio_transcription_node,
    ),
    NodeType.LLM_NODE: ("llm_node_list", copy_llm_node),
    NodeType.CREW_NODE: ("crew_node_list", copy_crew_node),
    NodeType.SUBGRAPH_NODE: ("subgraph_node_list", copy_subgraph_node),
    NodeType.PYTHON_NODE: ("python_node_list", copy_python_node),
    NodeType.WEBHOOK_TRIGGER_NODE: (
        "webhook_trigger_node_list",
        copy_webhook_trigger_node,
    ),
    NodeType.TELEGRAM_TRIGGER_NODE: (
        "telegram_trigger_node_list",
        copy_telegram_trigger_node,
    ),
    NodeType.DECISION_TABLE_NODE: (
        "decision_table_node_list",
        copy_decision_table_node,
    ),
    NodeType.CODE_AGENT_NODE: (
        "code_agent_node_list",
        copy_code_agent_node,
    ),
}
