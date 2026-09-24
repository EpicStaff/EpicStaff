/**
 * Turns the dialog's input snapshot into an explain request.
 *
 * Built from the snapshot, never from `CdtTreeBlock`: the tree carries strings
 * shaped for drawing — clamped subtitles, a manipulation composed into display
 * form, a prompt body with `→ stored in x` appended — and the backend wants the
 * fields. Sending the drawn form makes the model explain the picture, and prints
 * every assignment twice.
 *
 * Pure and Angular-free, like the builder beside it.
 */

import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { resolveLlmLabel } from '../cdt-llm-label.util';
import {
    enabledRowsInOrder,
    resolveNodeLabel,
    resolveRowTargets,
    rowManipulation,
    sortRowsByOrder,
} from './cdt-decision-tree.builder';
import { CDT_TREE_COPY } from './cdt-decision-tree.constants';
import { CdtDecisionTreeInput } from './cdt-decision-tree.model';
import { CdtExplainBlock, CdtExplainRule, CdtExplainTable } from './cdt-explain.model';

/** A multiple of the server's own batch size of six, well under its 100 cap. */
const CHUNK_SIZE = 30;

/**
 * Splits one Explain All pass into requests.
 *
 * Grouped by block type before slicing, because the server batches by the prompt
 * section a type belongs to and cuts each group at six — a mixed request just
 * produces more half-empty batches. Chunked rather than capped because over
 * `MAX_BLOCKS = 100` the whole request is a 400, not a truncation.
 */
export function chunkExplainBlocks(blocks: readonly CdtExplainBlock[], size = CHUNK_SIZE): CdtExplainBlock[][] {
    const byType = new Map<string, CdtExplainBlock[]>();
    for (const block of blocks) {
        const group = byType.get(block.block);
        if (group) group.push(block);
        else byType.set(block.block, [block]);
    }

    const chunks: CdtExplainBlock[][] = [];
    for (const group of byType.values()) {
        for (let start = 0; start < group.length; start += size) {
            chunks.push(group.slice(start, start + size));
        }
    }
    return chunks;
}

/**
 * Every step of the table, keyed by the block id the diagram gave it — the canvas
 * selects by that id and the response comes back under it.
 *
 * Ids come from walking `enabledRowsInOrder`, never from parsing `row-<i>:*` back
 * into an index: that index is a position after the hidden-row filter and the
 * order sort, so re-deriving it elsewhere would explain the wrong rule.
 */
export function buildCdtExplainBlocks(input: CdtDecisionTreeInput): ReadonlyMap<string, CdtExplainBlock> {
    const blocks = new Map<string, CdtExplainBlock>();

    const preCode = input.preCode?.trim() ?? '';
    if (preCode) {
        blocks.set('spine:pre-computation', {
            id: 'spine:pre-computation',
            block: 'pre_computation',
            code: input.preCode,
            input_map: input.preInputMap ?? {},
            output_variable_path: input.preOutputVariablePath,
            libraries: input.preLibraries,
        });
    }

    const postCode = input.postCode?.trim() ?? '';
    if (postCode) {
        // Drawn once per exit column when the table has post code and routes a
        // rule: same content under two ids.
        for (const id of ['exit:default:post', 'exit:route:post']) {
            blocks.set(id, {
                id,
                block: 'post_computation',
                code: input.postCode,
                input_map: input.postInputMap ?? {},
                output_variable_path: input.postOutputVariablePath,
                libraries: input.postLibraries,
            });
        }
    }

    const rows = enabledRowsInOrder(input.rows);
    const targets = resolveRowTargets(input);
    const names = ruleNames(input);

    rows.forEach((row, index) => {
        const name = names.get(row) ?? CDT_TREE_COPY.ruleFallback(index + 1);
        const target = targets[index];
        const manipulation = rowManipulation(row);

        blocks.set(`row-${index}:decision`, {
            id: `row-${index}:decision`,
            block: 'condition',
            rule_name: name,
            order: row.order ?? index + 1,
            enabled: true,
            // Raw halves: the backend merges them and drops duplicates itself.
            expression: row.expression?.trim() ?? '',
            field_expressions: row.field_expressions ?? {},
            on_match: {
                prompt: row.prompt_id ?? null,
                sets_variables: manipulation.length > 0,
                // A name, not an id. Unset means the table default applies.
                goes_to: target?.state === 'node' ? target.label : null,
            },
            continue_after_match: row.continue_flag ?? row.continue ?? false,
            // Only the last drawn rule falls through to the table default.
            on_no_match: index + 1 >= rows.length ? 'default_exit' : null,
            route_code: row.route_code?.trim() || null,
        });

        const prompt = row.prompt_id ? input.prompts?.[row.prompt_id] : undefined;
        if (row.prompt_id && prompt) {
            blocks.set(`row-${index}:prompt`, {
                id: `row-${index}:prompt`,
                block: 'prompt',
                rule_name: name,
                prompt_key: row.prompt_id,
                model: resolveLlmLabel(prompt.llm_config, input.llmConfigOptions),
                result_variable: prompt.result_variable,
                result_mappings: prompt.variable_mappings ?? {},
                answer_schema: Object.keys(prompt.output_schema ?? {}).length > 0,
                text: prompt.prompt_text ?? '',
            });
        }

        if (manipulation) {
            blocks.set(`row-${index}:manipulation`, {
                id: `row-${index}:manipulation`,
                block: 'manipulation',
                rule_name: name,
                // Raw again: the backend prints both halves on their own lines.
                assignments: row.manipulation?.trim() ?? '',
                field_assignments: row.field_manipulations ?? {},
            });
        }
    });

    return blocks;
}

/**
 * The table the step belongs to. `rules` includes hidden ones — the backend marks
 * them `DISABLED — never checked`, which is what explains an unreachable rule.
 */
export function buildCdtExplainTable(input: CdtDecisionTreeInput): CdtExplainTable {
    const names = ruleNames(input);

    const rules: CdtExplainRule[] = sortRowsByOrder(input.rows).map((row, index) => ({
        order: row.order ?? index + 1,
        name: names.get(row) ?? CDT_TREE_COPY.ruleFallback(index + 1),
        enabled: row.dock_visible !== false,
    }));

    return {
        node_name: input.nodeName,
        default_next_node: input.defaultNextNode ? resolveNodeLabel(input.defaultNextNode, input.nodes) : null,
        error_next_node: input.errorNextNode ? resolveNodeLabel(input.errorNextNode, input.nodes) : null,
        default_model: resolveLlmLabel(input.defaultLlmConfig, input.llmConfigOptions),
        rules,
    };
}

/**
 * The initial choice for which LLM writes the explanations: the table's default,
 * else the model one of its prompts runs on. Both are settings someone made on
 * this node; "the first config in the workspace" was tried and reverted, because
 * it can land on one with no API key and fail with no cause the user can see.
 * The picker overrides whatever this returns.
 */
export function resolveExplainLlmConfig(input: CdtDecisionTreeInput): number | null {
    if (input.defaultLlmConfig != null) return input.defaultLlmConfig;

    for (const prompt of Object.values(input.prompts ?? {})) {
        if (prompt?.llm_config != null) return prompt.llm_config;
    }

    return null;
}

/**
 * One name per rule, shared by the rules list and the condition blocks. A blank
 * name falls back to its position among the *drawn* rules, so the payload says
 * `Rule 3` for the block the canvas also labels `Rule 3`.
 */
function ruleNames(input: CdtDecisionTreeInput): ReadonlyMap<ConditionGroup, string> {
    const names = new Map<ConditionGroup, string>();

    sortRowsByOrder(input.rows).forEach((row, index) => {
        names.set(row, row.group_name?.trim() || CDT_TREE_COPY.ruleFallback(index + 1));
    });

    enabledRowsInOrder(input.rows).forEach((row, index) => {
        if (!row.group_name?.trim()) names.set(row, CDT_TREE_COPY.ruleFallback(index + 1));
    });

    return names;
}
