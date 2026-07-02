import { v4 as uuidv4 } from 'uuid';

import { GetClassificationDecisionTableNodeRequest } from '../../../../pages/flows-page/components/flow-visual-programming/models/classification-decision-table-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { ClassificationDecisionTableNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapClassificationDecisionTableNodeToModel(
    n: GetClassificationDecisionTableNodeRequest
): ClassificationDecisionTableNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(
        n.metadata as Record<string, unknown> | undefined,
        NodeType.CLASSIFICATION_TABLE
    );
    return {
        id: uuidv4(),
        backendId: n.id,
        type: NodeType.CLASSIFICATION_TABLE,
        node_name: n.node_name,
        nodeNumber: ui.nodeNumber,
        data: {
            name: n.node_name,
            table: {
                pre_computation_code: n.pre_python_code?.code ?? null,
                pre_input_map: n.pre_input_map ?? {},
                pre_output_variable_path: n.pre_output_variable_path,
                post_computation_code: n.post_python_code?.code ?? null,
                post_input_map: n.post_input_map ?? {},
                post_output_variable_path: n.post_output_variable_path,
                prompts: (() => {
                    const dict: Record<string, unknown> = {};
                    for (const p of n.prompt_configs ?? []) {
                        dict[p.prompt_key] = {
                            backendId: p.id,
                            prompt_text: p.prompt_text ?? '',
                            llm_config: p.llm_config ?? null,
                            output_schema: p.output_schema ?? null,
                            result_variable: p.result_variable ?? '',
                            variable_mappings: p.variable_mappings ?? {},
                        };
                    }
                    return dict;
                })(),
                default_llm_config: n.default_llm_config ?? null,
                default_next_node: null, // resolved in ref-resolvers/classification-decision-table-refs.ts
                next_error_node: null, // resolved in ref-resolvers/classification-decision-table-refs.ts
                pre_computation: {
                    code: n.pre_python_code?.code ?? '',
                    input_map: n.pre_input_map ?? {},
                    output_variable_path: n.pre_output_variable_path ?? null,
                    libraries: n.pre_python_code?.libraries ?? [],
                },
                post_computation: {
                    code: n.post_python_code?.code ?? '',
                    input_map: n.post_input_map ?? {},
                    output_variable_path: n.post_output_variable_path ?? null,
                    libraries: n.post_python_code?.libraries ?? [],
                },
                condition_groups: n.condition_groups.map((g) => ({
                    group_name: g.group_name,
                    order: g.order,
                    expression: g.expression,
                    prompt_id: n.prompt_configs.find((p) => p.id === g.prompt)?.prompt_key ?? null,
                    manipulation: g.manipulation,
                    continue_flag: g.continue_flag,
                    route_code: g.route_code ?? null,
                    dock_visible: g.dock_visible,
                    field_expressions: g.field_expressions ?? {},
                    field_manipulations: g.field_manipulations ?? {},
                    section: g.section ?? null,
                    next_node: null, // resolved in ref-resolvers/classification-decision-table-refs.ts
                })),
            },
        },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: {},
        output_variable_path: null,
        size: ui.size,
    };
}
