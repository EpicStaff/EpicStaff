from tables.models import (
    PythonNode,
    CrewNode,
    Graph,
    WebhookTriggerNode,
    TelegramTriggerNode,
    EndNode,
    WebhookTrigger,
    DecisionTableNode,
    SubGraphNode,
    ClassificationDecisionTableNode,
)
from tables.models.graph_models import (
    GraphNote,
    ClassificationConditionGroup,
    ClassificationDecisionTablePrompt,
)
from tables.import_export.enums import NodeType, EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.python_tools import PythonCodeImportSerializer
from tables.models.graph_models import CodeAgentNode
from tables.import_export.serializers.graph import (
    StartNodeImportSerializer,
    CrewNodeImportSerializer,
    PythonNodeImportSerializer,
    LLMNodeImportSerializer,
    CodeAgentNodeImportSerializer,
    WebhookTriggerNodeImportSerializer,
    FileExtractorNodeImportSerializer,
    AudioTranscriptionNodeImportSerializer,
    DecisionTableNodeImportSerializer,
    TelegramTriggerNodeImportSerializer,
    TelegramTriggerNodeFieldImportSerializer,
    EndNodeImportSerializer,
    ConditionGroupImportSerializer,
    ConditionImportSerializer,
    SubgraphNodeImportSerializer,
    GraphNoteImportSerializer,
    ClassificationDecisionTableNodeImportSerializer,
    ClassificationConditionGroupImportSerializer,
)


def import_python_node(
    graph: Graph, node_data: dict, id_mapper: IDMapper
) -> PythonNode:
    python_code_data = node_data.pop("python_code", None)

    serializer = PythonCodeImportSerializer(data=python_code_data)
    serializer.is_valid(raise_exception=True)
    python_code = serializer.save()

    serializer = PythonNodeImportSerializer(
        data={**node_data, "graph": graph.id, "python_code_id": python_code.id}
    )
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def import_crew_node(graph: Graph, node_data: dict, id_mapper: IDMapper) -> CrewNode:
    crew_id = node_data.pop("crew", None)

    new_crew_id = id_mapper.get_or_none(EntityType.CREW, crew_id)
    node_data["crew"] = new_crew_id

    serializer = CrewNodeImportSerializer(data={**node_data, "graph": graph.id})
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def import_webhook_trigger_node(
    graph: Graph, node_data: dict, id_mapper: IDMapper
) -> WebhookTriggerNode:
    python_code_data = node_data.pop("python_code", None)
    old_trigger_id = node_data.pop("webhook_trigger", None)
    new_trigger_id = id_mapper.get_or_none(EntityType.WEBHOOK_TRIGGER, old_trigger_id)

    webhook_trigger = WebhookTrigger.objects.filter(id=new_trigger_id).first()
    webhook_trigger_id = getattr(webhook_trigger, "id", None)

    python_code_serializer = PythonCodeImportSerializer(data=python_code_data)
    python_code_serializer.is_valid(raise_exception=True)
    python_code = python_code_serializer.save()

    serializer = WebhookTriggerNodeImportSerializer(
        data={
            **node_data,
            "graph": graph.id,
            "python_code_id": python_code.id,
            "webhook_trigger_id": webhook_trigger_id,
        }
    )
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def import_end_node(graph: Graph, node_data: dict, id_mapper: IDMapper) -> EndNode:
    serializer = EndNodeImportSerializer(data={**node_data, "graph": graph.id})
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def import_decision_table_node(
    graph: Graph, node_data: dict, id_mapper: IDMapper
) -> DecisionTableNode:
    condition_groups_data = node_data.pop("condition_groups", [])

    serializer = DecisionTableNodeImportSerializer(
        data={**node_data, "graph": graph.id}
    )
    serializer.is_valid(raise_exception=True)
    decision_table_node = serializer.save()

    for group_data in condition_groups_data:
        conditions_data = group_data.pop("conditions", [])
        group_data["decision_table_node_id"] = decision_table_node.id

        group_serializer = ConditionGroupImportSerializer(data=group_data)
        group_serializer.is_valid(raise_exception=True)
        condition_group = group_serializer.save()

        for condition_data in conditions_data:
            condition_serializer = ConditionImportSerializer(data=condition_data)
            condition_serializer.is_valid(raise_exception=True)
            condition_serializer.save(condition_group=condition_group)

    return decision_table_node


def import_classification_decision_table_node(
    graph: Graph, node_data: dict, id_mapper: IDMapper
) -> ClassificationDecisionTableNode:
    condition_groups_data = node_data.pop("condition_groups", [])
    prompt_configs_data = node_data.pop("prompt_configs", [])

    pre_python_code_data = node_data.pop("pre_python_code", None)

    if pre_python_code_data:
        pre_serializer = PythonCodeImportSerializer(data=pre_python_code_data)
        pre_serializer.is_valid(raise_exception=True)
        node_data["pre_python_code_id"] = pre_serializer.save().id

    post_python_code_data = node_data.pop("post_python_code", None)

    if post_python_code_data:
        post_serializer = PythonCodeImportSerializer(data=post_python_code_data)
        post_serializer.is_valid(raise_exception=True)
        node_data["post_python_code_id"] = post_serializer.save().id

    default_llm_config_id = node_data.pop("default_llm_config", None)
    node_data["default_llm_config"] = id_mapper.get_or_none(
        EntityType.LLM_CONFIG, default_llm_config_id
    )

    serializer = ClassificationDecisionTableNodeImportSerializer(
        data={**node_data, "graph": graph.id}
    )
    serializer.is_valid(raise_exception=True)
    cdt_node = serializer.save()

    for group_data in condition_groups_data:
        group_data["classification_decision_table_node_id"] = cdt_node.id
        group_serializer = ClassificationConditionGroupImportSerializer(data=group_data)
        group_serializer.is_valid(raise_exception=True)
        group_serializer.save()

    ClassificationDecisionTablePrompt.objects.bulk_create(
        [
            ClassificationDecisionTablePrompt(
                cdt_node=cdt_node,
                prompt_key=pc["prompt_key"],
                prompt_text=pc.get("prompt_text", ""),
                llm_config_id=id_mapper.get_or_none(
                    EntityType.LLM_CONFIG, pc.get("llm_config")
                ),
                output_schema=pc.get("output_schema", {}),
                result_variable=pc.get("result_variable", "prompt_result"),
                variable_mappings=pc.get("variable_mappings", {}),
            )
            for pc in prompt_configs_data
        ]
    )

    return cdt_node


def import_telegram_trigger_node(
    graph: Graph, node_data: dict, id_mapper: IDMapper
) -> TelegramTriggerNode:
    fields_data = node_data.pop("fields", [])

    serializer = TelegramTriggerNodeImportSerializer(
        data={**node_data, "graph": graph.id}
    )
    serializer.is_valid(raise_exception=True)
    telegram_trigger_node = serializer.save()

    serializer = TelegramTriggerNodeFieldImportSerializer(data=fields_data, many=True)
    serializer.is_valid(raise_exception=True)
    serializer.save(telegram_trigger_node=telegram_trigger_node)

    return telegram_trigger_node


def import_code_agent_node(
    graph: Graph, node_data: dict, id_mapper: IDMapper
) -> CodeAgentNode:
    llm_config_id = node_data.pop("llm_config", None)

    new_llm_config_id = id_mapper.get_or_none(EntityType.LLM_CONFIG, llm_config_id)
    node_data["llm_config"] = new_llm_config_id

    serializer = CodeAgentNodeImportSerializer(data={**node_data, "graph": graph.id})
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def import_subgraph_node(
    graph: Graph, node_data: dict, id_mapper: IDMapper
) -> SubGraphNode:
    subgraph_id = id_mapper.get_or_none(EntityType.GRAPH, node_data["subgraph"])

    serializer = SubgraphNodeImportSerializer(
        data={**node_data, "graph": graph.id, "subgraph": subgraph_id}
    )
    serializer.is_valid(raise_exception=True)
    return serializer.save()


NODE_HANDLERS = {
    NodeType.CREW_NODE: {
        "serializer": CrewNodeImportSerializer,
        "relation": "crew_node_list",
        "import_hook": import_crew_node,
    },
    NodeType.SUBGRAPH_NODE: {
        "serializer": SubgraphNodeImportSerializer,
        "relation": "subgraph_node_list",
        "import_hook": import_subgraph_node,
    },
    NodeType.PYTHON_NODE: {
        "serializer": PythonNodeImportSerializer,
        "relation": "python_node_list",
        "import_hook": import_python_node,
    },
    NodeType.LLM_NODE: {
        "serializer": LLMNodeImportSerializer,
        "relation": "llm_node_list",
    },
    NodeType.WEBHOOK_TRIGGER_NODE: {
        "serializer": WebhookTriggerNodeImportSerializer,
        "relation": "webhook_trigger_node_list",
        "import_hook": import_webhook_trigger_node,
    },
    NodeType.FILE_EXTRACTOR_NODE: {
        "serializer": FileExtractorNodeImportSerializer,
        "relation": "file_extractor_node_list",
    },
    NodeType.AUDIO_TRANSCRIPTION_NODE: {
        "serializer": AudioTranscriptionNodeImportSerializer,
        "relation": "audio_transcription_node_list",
    },
    NodeType.START_NODE: {
        "serializer": StartNodeImportSerializer,
        "relation": "start_node_list",
    },
    NodeType.DECISION_TABLE_NODE: {
        "serializer": DecisionTableNodeImportSerializer,
        "relation": "decision_table_node_list",
        "import_hook": import_decision_table_node,
    },
    NodeType.CLASSIFICATION_DECISION_TABLE_NODE: {
        "serializer": ClassificationDecisionTableNodeImportSerializer,
        "relation": "classification_decision_table_node_list",
        "import_hook": import_classification_decision_table_node,
    },
    NodeType.TELEGRAM_TRIGGER_NODE: {
        "serializer": TelegramTriggerNodeImportSerializer,
        "relation": "telegram_trigger_node_list",
        "import_hook": import_telegram_trigger_node,
    },
    NodeType.END_NODE: {
        "serializer": EndNodeImportSerializer,
        "relation": "end_node",
        "import_hook": import_end_node,
    },
    NodeType.NOTE_NODE: {
        "serializer": GraphNoteImportSerializer,
        "relation": "graph_note_list",
    },
    NodeType.CODE_AGENT_NODE: {
        "serializer": CodeAgentNodeImportSerializer,
        "relation": "code_agent_node_list",
        "import_hook": import_code_agent_node,
    },
}
