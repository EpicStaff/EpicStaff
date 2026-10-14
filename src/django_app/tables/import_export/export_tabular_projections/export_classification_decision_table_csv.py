import csv
import io

from tables.import_export.export_tabular_projections._csv_helpers import (
    _format_mapping,
    _llm_config_label,
    _neutralize_formula,
    _node_label,
    _node_labels,
    _yes_no,
)
from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
)

RULE_COLUMNS = [
    "#",
    "Rule Name",
    "Section",
    "Route Code",
    "Condition",
    "AI Prompt",
    "AI Model",
    "Saves Result To",
    "Action",
    "Field Conditions",
    "Field Actions",
    "Continue After Match",
    "Next Step",
]

LLM_CONFIG_COLUMNS = ["Configuration Name", "Model", "Temperature", "Max Tokens"]


def _collect_llm_configs(
    node: ClassificationDecisionTableNode,
    groups: list[ClassificationConditionGroup],
) -> list:
    configs = {}
    if node.default_llm_config:
        configs[node.default_llm_config_id] = node.default_llm_config
    for group in groups:
        if group.prompt and group.prompt.llm_config:
            configs[group.prompt.llm_config_id] = group.prompt.llm_config
    return list(configs.values())


def rule_row(
    number: int,
    group: ClassificationConditionGroup,
    node_names: dict[int, str],
) -> list:
    prompt = group.prompt
    return [
        number,
        group.group_name,
        group.section.name if group.section else "",
        group.route_code or "",
        group.expression or "",
        prompt.prompt_text if prompt else "",
        _llm_config_label(prompt.llm_config) if prompt else "",
        prompt.result_variable if prompt else "",
        group.manipulation or "",
        _format_mapping(group.field_expressions),
        _format_mapping(group.field_manipulations),
        _yes_no(group.continue_flag),
        _node_label(group.next_node_id, node_names),
    ]


def export_condition_groups_csv(node: ClassificationDecisionTableNode) -> io.StringIO:
    groups = list(
        node.condition_groups.select_related("prompt__llm_config__model").order_by("order")
    )
    node_names = _node_labels(
        [
            node.default_next_node_id,
            node.next_error_node_id,
            *(group.next_node_id for group in groups),
        ],
        node.graph_id,
    )

    buf = io.StringIO()
    writer = csv.writer(buf)

    def write(row: list) -> None:
        writer.writerow([_neutralize_formula(value) for value in row])

    write(["CLASSIFICATION DECISION TABLE"])
    write(["Node Name", node.node_name])
    write(["Default AI Model", _llm_config_label(node.default_llm_config)])
    write(["Pre-processing Script", _yes_no(node.pre_python_code_id)])
    write(["Post-processing Script", _yes_no(node.post_python_code_id)])
    write(["Default Next Step", _node_label(node.default_next_node_id, node_names)])
    write(["On Error Go To", _node_label(node.next_error_node_id, node_names)])
    write(["Number of Rules", len(groups)])
    write([])

    llm_configs = _collect_llm_configs(node, groups)
    if llm_configs:
        write(["AI MODELS USED"])
        write(LLM_CONFIG_COLUMNS)
        for config in llm_configs:
            write(
                [
                    config.custom_name,
                    config.model.name if config.model else "",
                    config.temperature,
                    config.max_tokens,
                ]
            )
        write([])

    write(["DECISION RULES"])
    write(RULE_COLUMNS)
    for number, group in enumerate(groups, start=1):
        write(rule_row(number, group, node_names))

    return buf
