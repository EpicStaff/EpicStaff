/**
 * Wire contracts of the Classification Decision Table explanation endpoints:
 * `POST …/{pk}/explain/` (generate) and `PUT …/{pk}/explanations/` (persist).
 *
 * Field names are the backend's and several differ from this app's:
 * `manipulation` → `assignments`, `field_manipulations` → `field_assignments`,
 * `continue_flag` → `continue_after_match`, `prompt_text` → `text`,
 * `variable_mappings` → `result_mappings`.
 *
 * That renaming is why these types exist. The explain serializer validates only
 * `id` and `block` and passes every other key straight to the prompt renderer, so
 * a misspelt field is not a 400 — it is a 200 explaining less than the whole step.
 */

import { CdtExplanations } from './classification-decision-table.model';

/** The five step kinds the backend can explain (`SUPPORTED_BLOCK_TYPES`). */
export type CdtExplainBlockType = 'pre_computation' | 'post_computation' | 'condition' | 'prompt' | 'manipulation';

// ---------------------------------------------------------------------------
// Explain — request
// ---------------------------------------------------------------------------

export interface CdtExplainRule {
    readonly order: number;
    readonly name: string;
    /** Hidden rules are sent too — the backend prints them as never checked. */
    readonly enabled: boolean;
}

export interface CdtExplainTable {
    readonly node_name: string;
    /** A node **name**, not an id — the backend quotes it into the prompt. */
    readonly default_next_node: string | null;
    readonly error_next_node: string | null;
    /** A human label such as `gpt-4o-mini`, not a config id. */
    readonly default_model: string;
    readonly rules: readonly CdtExplainRule[];
}

interface CdtExplainBlockBase {
    /** Echoed back on the response, and how an explanation finds its block. */
    readonly id: string;
}

export interface CdtExplainComputationBlock extends CdtExplainBlockBase {
    readonly block: 'pre_computation' | 'post_computation';
    readonly code: string;
    readonly input_map: Readonly<Record<string, string>>;
    readonly output_variable_path: string | null;
}

export interface CdtExplainConditionBlock extends CdtExplainBlockBase {
    readonly block: 'condition';
    readonly rule_name: string;
    readonly order: number;
    readonly enabled: boolean;
    /** Raw, not merged with `field_expressions` — the backend does that itself. */
    readonly expression: string;
    readonly field_expressions: Readonly<Record<string, string>>;
    readonly on_match: {
        readonly prompt: string | null;
        readonly sets_variables: boolean;
        /** A node name, or null when the rule routes nowhere. */
        readonly goes_to: string | null;
    };
    readonly continue_after_match: boolean;
    /** Only the last drawn rule falls through to the table default. */
    readonly on_no_match: 'default_exit' | null;

    readonly route_code: string | null;
}

export interface CdtExplainPromptBlock extends CdtExplainBlockBase {
    readonly block: 'prompt';
    readonly rule_name: string;
    readonly prompt_key: string;
    readonly model: string;
    readonly result_variable: string;
    readonly result_mappings: Readonly<Record<string, string>>;
    readonly answer_schema: boolean;
    readonly text: string;
}

export interface CdtExplainManipulationBlock extends CdtExplainBlockBase {
    readonly block: 'manipulation';
    readonly rule_name: string;
    /** Raw, not the composed display form — see the payload builder. */
    readonly assignments: string;
    readonly field_assignments: Readonly<Record<string, string>>;
}

export type CdtExplainBlock =
    | CdtExplainComputationBlock
    | CdtExplainConditionBlock
    | CdtExplainPromptBlock
    | CdtExplainManipulationBlock;

export interface CdtExplainRequest {
    readonly llm_config: number;
    readonly table: CdtExplainTable;
    readonly blocks: readonly CdtExplainBlock[];
}

// ---------------------------------------------------------------------------
// Explain — response
// ---------------------------------------------------------------------------

export interface CdtExplainedStep {
    readonly id: string;
    readonly text: string;
    /** The backend's own label for the model, not one the FE recomputes. */
    readonly generated_by: string;
}

export interface CdtExplainFailure {
    readonly id: string;
    readonly detail: string;
}

/** A 200 can carry both: one batch can fail while the rest succeed. */
export interface CdtExplainResponse {
    readonly explanations: readonly CdtExplainedStep[];
    readonly failures: readonly CdtExplainFailure[];
}

// ---------------------------------------------------------------------------
// Persisting explanations
// ---------------------------------------------------------------------------

/**
 * Replaces the node's `metadata.explanations` and nothing else, so persisting an
 * explanation never persists the table edits it was generated against. Versioned
 * like a bulk save: a stale `save_version` is a 409, a success bumps it.
 */
export interface CdtExplanationsSaveRequest {
    readonly save_version: number;
    /** The complete map; `{}` clears it. */
    readonly explanations: CdtExplanations;
}

export interface CdtExplanationsSaveResponse {
    readonly explanations: CdtExplanations;
    readonly save_version: number;
}
