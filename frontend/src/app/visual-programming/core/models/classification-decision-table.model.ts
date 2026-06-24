import { ConditionGroup } from './decision-table.model';

export interface ComputationConfig {
    code: string;
    input_map?: Record<string, string>;
    output_variable_path?: string;
    libraries?: string[];
}

export interface ClassificationDecisionTableData {
    pre_computation_code: string;
    pre_input_map?: Record<string, string>;
    pre_output_variable_path?: string;
    post_computation_code?: string;
    post_input_map?: Record<string, string>;
    post_output_variable_path?: string;
    pre_computation?: ComputationConfig;
    post_computation?: ComputationConfig;
    condition_groups: ConditionGroup[];
    route_variable_name: string;
    default_next_node: string | null;
    next_error_node: string | null;
    default_llm_config?: number | null;
    expression_errors_as_false?: boolean;
    prompts?: Record<string, PromptConfig>;
    output_variables?: OutputVariableMapping[];
}

export interface DecisionTableRow {
    id: string;
    rule_name: string;
    conditions: Record<string, string>;
    manipulation: string;
    route_name: string;
    loop: 'stop' | 'continue';
}

export interface InputVariableMapping {
    table_variable: string;
    source_path: string;
}

export interface OutputVariableMapping {
    target_path: string;
    table_variable: string;
}

export interface PromptConfig {
    prompt_text: string;
    llm_config: number | null;
    output_schema: Record<string, unknown> | string | null;
    result_variable: string;
    variable_mappings: Record<string, string>;
}
