from typing import Optional

from tables.models import ClassificationDecisionTableNode
from tables.models.graph_models import ClassificationDecisionTablePrompt
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.classification_decision_table_node import (
    ClassificationDecisionTableNodeImportSerializer,
    ClassificationConditionGroupImportSerializer,
)
from tables.import_export.serializers.python_tools import PythonCodeImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper


class ClassificationDecisionTableNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.CLASSIFICATION_DECISION_TABLE_NODE
    serializer_class = ClassificationDecisionTableNodeImportSerializer

    def get_instance(self, entity_id: int) -> Optional[ClassificationDecisionTableNode]:
        return ClassificationDecisionTableNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: ClassificationDecisionTableNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(
        self, instance: ClassificationDecisionTableNode
    ) -> dict:
        deps = {EntityType.GRAPH: [instance.graph_id]}
        llm_config_ids = set()
        if instance.default_llm_config_id:
            llm_config_ids.add(instance.default_llm_config_id)
        llm_config_ids |= set(
            ClassificationDecisionTablePrompt.objects.filter(
                cdt_node=instance
            ).values_list("llm_config_id", flat=True)
        )
        llm_config_ids.discard(None)
        if llm_config_ids:
            deps[EntityType.LLM_CONFIG] = list(llm_config_ids)
        return deps

    def export_entity(self, instance: ClassificationDecisionTableNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(
        self, data: dict, id_mapper: IDMapper, **kwargs
    ) -> ClassificationDecisionTableNode:
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))
        condition_groups_data = data.pop("condition_groups", [])
        prompt_configs_data = data.pop("prompt_configs", [])

        pre_python_code_data = data.pop("pre_python_code", None)
        if pre_python_code_data:
            pre_serializer = PythonCodeImportSerializer(data=pre_python_code_data)
            pre_serializer.is_valid(raise_exception=True)
            data["pre_python_code_id"] = pre_serializer.save().id

        post_python_code_data = data.pop("post_python_code", None)
        if post_python_code_data:
            post_serializer = PythonCodeImportSerializer(data=post_python_code_data)
            post_serializer.is_valid(raise_exception=True)
            data["post_python_code_id"] = post_serializer.save().id

        old_llm_config_id = data.pop("default_llm_config", None)
        data["default_llm_config"] = id_mapper.get_or_none(
            EntityType.LLM_CONFIG, old_llm_config_id
        )

        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        node = serializer.save()

        prompt_id_mapping = {}
        for pc in prompt_configs_data:
            old_id = pc.get("id")
            prompt = ClassificationDecisionTablePrompt.objects.create(
                cdt_node=node,
                prompt_key=pc["prompt_key"],
                prompt_text=pc.get("prompt_text", ""),
                llm_config_id=id_mapper.get_or_none(
                    EntityType.LLM_CONFIG, pc.get("llm_config")
                ),
                output_schema=pc.get("output_schema", {}),
                result_variable=pc.get("result_variable", "prompt_result"),
                variable_mappings=pc.get("variable_mappings", {}),
            )
            if old_id is not None:
                prompt_id_mapping[old_id] = prompt.id

        for group_data in condition_groups_data:
            group_data["classification_decision_table_node_id"] = node.id
            old_prompt_id = group_data.get("prompt")
            if old_prompt_id is not None:
                group_data["prompt"] = prompt_id_mapping.get(old_prompt_id)
            group_serializer = ClassificationConditionGroupImportSerializer(
                data=group_data
            )
            group_serializer.is_valid(raise_exception=True)
            group_serializer.save()

        return node
