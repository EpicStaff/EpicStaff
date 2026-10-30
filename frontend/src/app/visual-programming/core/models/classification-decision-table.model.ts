import { CdtSection } from './cdt-section.model';
import { ConditionGroup } from './decision-table.model';

export interface ComputationConfig {
    code: string;
    /** Stored with the code and sent back as loaded (the panel does not edit them); absent for new code. */
    entrypoint?: string;
    global_kwargs?: Record<string, unknown>;
    input_map?: Record<string, string>;
    output_variable_path?: string | null;
    secret_ids?: number[];
    secret_names?: string[];
    /** Seconds one run of the code may take; absent until set, then the backend applies its default. */
    execution_timeout?: number;
}

export interface ClassificationDecisionTableData {
    pre_computation_code: string | null;
    pre_input_map?: Record<string, string>;
    pre_output_variable_path?: string | null;
    pre_use_storage?: boolean;
    post_computation_code?: string | null;
    post_input_map?: Record<string, string>;
    post_output_variable_path?: string | null;
    post_use_storage?: boolean;
    pre_computation?: ComputationConfig;
    post_computation?: ComputationConfig;
    condition_groups: ConditionGroup[];
    sections?: CdtSection[];
    route_variable_name?: string;
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
    backendId?: number;
    prompt_text: string;
    llm_config: number | null;
    output_schema: Record<string, unknown> | string | null;
    result_variable: string;
    variable_mappings: Record<string, string>;
    output_schema_invalid?: boolean;
}

/**
 * One generated explanation of a decision-tree step. Lives in the node's
 * `metadata.explanations`, so it travels with the graph rather than with the
 * browser that generated it.
 */
export interface CdtExplanation {
    readonly text: string;
    /** The step's fingerprint when this text was generated. Differs → outdated. */
    readonly fingerprint: string;
    readonly generatedBy: string;
}

/** Keyed by step identity — see `buildExplainStepKeys` for why the key is what it is. */
export type CdtExplanations = Readonly<Record<string, CdtExplanation>>;

/**
 * One step's explanation re-filed after an edit changed the key its rule is filed
 * under — see `explainKeyMovesForRuleEdit`.
 */
export interface CdtExplanationKeyMove {
    readonly from: string;
    readonly to: string;
}
