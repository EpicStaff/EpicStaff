export interface PromptConfigBackend {
    id: number;
    prompt_key: string;
    prompt_text: string;
    llm_config: number | null;
    output_schema: Record<string, unknown> | string | null;
    result_variable: string;
    variable_mappings: Record<string, string>;
}

export interface CreatePromptConfigRequest {
    prompt_key: string;
    prompt_text: string;
    llm_config: number | null;
    output_schema: Record<string, unknown> | string | null;
    result_variable: string;
    variable_mappings: Record<string, string>;
}

export interface ClassificationConditionGroupBackend {
    id: number;
    classification_decision_table_node: number;
    group_name: string;
    order: number;
    expression: string | null;
    prompt: number | null;
    manipulation: string | null;
    continue_flag: boolean;
    route_code: string | null;
    dock_visible: boolean;
    field_expressions: Record<string, string>;
    field_manipulations: Record<string, string>;
    next_node_id?: number | null;
    section?: string | null;
}

export interface CreateClassificationConditionGroupRequest {
    group_name: string;
    order: number;
    expression: string | null;
    prompt: number | null;
    manipulation: string | null;
    continue_flag: boolean;
    route_code: string | null;
    next_node_id?: number | null;
    dock_visible: boolean;
    field_expressions: Record<string, string>;
    field_manipulations: Record<string, string>;
    section?: string | null;
}

export interface CDTPythonCodeBlock {
    libraries: string[];
    code: string;
    entrypoint: string;
    global_kwargs: Record<string, unknown>;
    content_hash?: string;
}

export interface GetClassificationDecisionTableNodeRequest {
    id: number;
    graph: number;
    node_name: string;
    pre_python_code: CDTPythonCodeBlock | null;
    pre_input_map: Record<string, string>;
    pre_output_variable_path: string | null;
    post_python_code: CDTPythonCodeBlock | null;
    post_input_map: Record<string, string>;
    post_output_variable_path: string | null;
    prompt_configs: PromptConfigBackend[];
    default_llm_config: number | null;
    default_next_node_id: number | null;
    next_error_node_id: number | null;
    condition_groups: ClassificationConditionGroupBackend[];
    metadata?: unknown;
}

export interface CreateClassificationDecisionTableNodeRequest {
    graph: number;
    node_name: string;
    pre_python_code: CDTPythonCodeBlock | null;
    pre_input_map: Record<string, string> | null;
    pre_output_variable_path: string | null;
    post_python_code: CDTPythonCodeBlock | null;
    post_input_map: Record<string, string> | null;
    post_output_variable_path: string | null;
    prompt_configs: CreatePromptConfigRequest[];
    default_llm_config: number | null;
    default_next_node_id?: number | null;
    default_next_node_temp_id?: string | null;
    next_error_node_id?: number | null;
    next_error_node_temp_id?: string | null;
    condition_groups: CreateClassificationConditionGroupRequest[];
    metadata?: unknown;
}
