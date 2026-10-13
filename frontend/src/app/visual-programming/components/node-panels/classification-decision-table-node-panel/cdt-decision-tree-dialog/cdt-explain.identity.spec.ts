import { PromptConfig } from '../../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { CdtDecisionTreeInput } from './cdt-decision-tree.model';
import { buildExplainStepKeys, explainStepFingerprint } from './cdt-explain.identity';
import { buildCdtExplainBlocks } from './cdt-explain.payload';

function row(overrides: Partial<ConditionGroup>): ConditionGroup {
    return {
        group_name: '',
        group_type: 'simple',
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        ...overrides,
    };
}

function prompt(overrides: Partial<PromptConfig> = {}): PromptConfig {
    return {
        prompt_text: 'Classify the ticket',
        llm_config: null,
        output_schema: null,
        result_variable: 'category',
        variable_mappings: {},
        ...overrides,
    };
}

function input(overrides: Partial<CdtDecisionTreeInput> = {}): CdtDecisionTreeInput {
    return {
        nodeId: 'table',
        backendId: 7,
        nodeName: 'Triage',
        preCode: '',
        postCode: '',
        preInputMap: {},
        postInputMap: {},
        preLibraries: [],
        postLibraries: [],
        preOutputVariablePath: null,
        postOutputVariablePath: null,
        prompts: {},
        rows: [],
        canvasRows: [],
        defaultNextNode: null,
        errorNextNode: null,
        connections: [],
        nodes: [],
        defaultLlmConfig: null,
        llmConfigOptions: [],
        readOnly: false,
        ...overrides,
    };
}

function keysOf(rows: ConditionGroup[], overrides: Partial<CdtDecisionTreeInput> = {}): ReadonlyMap<string, string> {
    return buildExplainStepKeys(input({ rows, ...overrides }));
}

function decisionFingerprint(source: CdtDecisionTreeInput, id = 'row-0:decision'): string {
    const block = buildCdtExplainBlocks(source).get(id);
    if (!block) throw new Error(`no explain block "${id}"`);
    return explainStepFingerprint(block);
}

describe('buildExplainStepKeys', () => {
    it('keys a rule by the slug of its route code first', () => {
        const keys = keysOf([row({ group_name: 'Escalate', route_code: 'Needs Review' })]);

        expect(keys.get('row-0:decision')).toBe('rule:route:needs-review:decision');
        expect(keys.get('row-0:prompt')).toBe('rule:route:needs-review:prompt');
        expect(keys.get('row-0:manipulation')).toBe('rule:route:needs-review:manipulation');
    });

    it('keeps the key when the rule is renamed, as long as its route code holds', () => {
        const before = keysOf([row({ group_name: 'Escalate', route_code: 'review' })]);
        const after = keysOf([row({ group_name: 'Escalate now', route_code: 'review' })]);

        expect(after.get('row-0:decision')).toBe(before.get('row-0:decision'));
    });

    it('falls back to the trimmed name when there is no route code', () => {
        const keys = keysOf([row({ group_name: '  Spam  ', route_code: '   ' })]);

        expect(keys.get('row-0:decision')).toBe('rule:name:Spam:decision');
    });

    it('treats Approve and approve as one route, so neither borrows the other key', () => {
        const keys = keysOf([
            row({ group_name: 'First', route_code: 'Approve', order: 1 }),
            row({ group_name: 'Second', route_code: 'approve', order: 2 }),
        ]);

        expect(keys.get('row-0:decision')).toBe('rule:name:First:decision');
        expect(keys.get('row-1:decision')).toBe('rule:name:Second:decision');
    });

    it('falls back to content when both the route code and the name are shared', () => {
        const keys = keysOf([
            row({ group_name: 'Same', route_code: 'x', expression: 'a > 1', order: 1 }),
            row({ group_name: 'Same', route_code: 'x', expression: 'a > 2', order: 2 }),
        ]);

        const first = keys.get('row-0:decision');
        const second = keys.get('row-1:decision');

        expect(first).toMatch(/^rule:content:.+:decision$/);
        expect(second).toMatch(/^rule:content:.+:decision$/);
        expect(first).not.toBe(second);
    });

    it('falls back to content for a blank name with no route code', () => {
        expect(keysOf([row({ group_name: '  ' })]).get('row-0:decision')).toMatch(/^rule:content:/);
    });

    it('keeps a content key across a reorder, since order is not identity', () => {
        const rows = [
            row({ group_name: 'Dup', expression: 'a', order: 1 }),
            row({ group_name: 'Dup', expression: 'b', order: 2 }),
        ];
        const before = keysOf(rows);
        const after = keysOf([
            { ...rows[0], order: 2 },
            { ...rows[1], order: 1 },
        ]);

        expect(after.get('row-1:decision')).toBe(before.get('row-0:decision'));
        expect(after.get('row-0:decision')).toBe(before.get('row-1:decision'));
    });

    it('counts names among drawn rules only, so a hidden duplicate does not disqualify the name', () => {
        const keys = keysOf([row({ group_name: 'Spam', dock_visible: false }), row({ group_name: 'Spam', order: 1 })]);

        expect(keys.get('row-0:decision')).toBe('rule:name:Spam:decision');
        expect(keys.has('row-1:decision')).toBe(false);
    });

    it('indexes rows by drawn position, after the hidden filter and the order sort', () => {
        const keys = keysOf([
            row({ group_name: 'Third', order: 3 }),
            row({ group_name: 'Hidden', order: 1, dock_visible: false }),
            row({ group_name: 'Second', order: 2 }),
        ]);

        expect(keys.get('row-0:decision')).toBe('rule:name:Second:decision');
        expect(keys.get('row-1:decision')).toBe('rule:name:Third:decision');
        expect(keys.has('row-2:decision')).toBe(false);
    });

    it('files both drawings of the post-computation under one key, and only when there is code', () => {
        expect(keysOf([], { preCode: '  ', postCode: '\n' }).size).toBe(0);

        const keys = keysOf([], { preCode: 'x = 1', postCode: 'y = 2' });

        expect(keys.get('spine:pre-computation')).toBe('node:pre');
        expect(keys.get('exit:default:post')).toBe('node:post');
        expect(keys.get('exit:route:post')).toBe('node:post');
    });

    it('has a key for every block the explain payload produces', () => {
        const source = input({
            preCode: 'a = 1',
            postCode: 'b = 2',
            prompts: { classify: prompt() },
            rows: [
                row({ group_name: 'A', prompt_id: 'classify', manipulation: 'x = 1', order: 1 }),
                row({ group_name: '', expression: 'y > 2', order: 2 }),
                row({ group_name: 'Hidden', dock_visible: false, manipulation: 'z = 3' }),
            ],
        });
        const keys = buildExplainStepKeys(source);

        for (const id of buildCdtExplainBlocks(source).keys()) {
            expect(keys.has(id), id).toBe(true);
        }
    });
});

describe('explainStepFingerprint', () => {
    const base = input({ rows: [row({ group_name: 'Rule', expression: 'a > 1', order: 1 })] });

    it('ignores the position of the rule', () => {
        const moved = input({
            rows: [
                row({ group_name: 'Earlier', order: 1 }),
                row({ group_name: 'Rule', expression: 'a > 1', order: 2 }),
            ],
        });

        // `order` changes and the id moves to row-1; the step itself does not.
        expect(decisionFingerprint(moved, 'row-1:decision')).toBe(decisionFingerprint(base));
    });

    it('ignores order alone on an otherwise identical block', () => {
        const block = buildCdtExplainBlocks(base).get('row-0:decision');
        if (!block || block.block !== 'condition') throw new Error('expected a condition block');

        expect(explainStepFingerprint({ ...block, order: 42, id: 'row-9:decision', on_no_match: null })).toBe(
            explainStepFingerprint(block)
        );
    });

    it('changes when what the step does changes', () => {
        const edited = input({ rows: [row({ group_name: 'Rule', expression: 'a > 2', order: 1 })] });

        expect(decisionFingerprint(edited)).not.toBe(decisionFingerprint(base));
    });

    it('does not depend on the key order of field expressions', () => {
        const ab = input({ rows: [row({ group_name: 'R', field_expressions: { a: '> 1', b: '< 2' } })] });
        const ba = input({ rows: [row({ group_name: 'R', field_expressions: { b: '< 2', a: '> 1' } })] });

        expect(decisionFingerprint(ba)).toBe(decisionFingerprint(ab));
    });
});
