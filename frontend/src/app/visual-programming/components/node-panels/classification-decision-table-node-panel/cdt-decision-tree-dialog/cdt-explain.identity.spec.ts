import { PromptConfig } from '../../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { CdtDecisionTreeInput } from './cdt-decision-tree.model';
import {
    buildExplainStepKeys,
    buildRetainedExplainStepKeys,
    explainKeyMovesForRuleEdit,
    explainStepFingerprint,
} from './cdt-explain.identity';
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

describe('explainKeyMovesForRuleEdit', () => {
    /** The rows with `rows[index]` changed — what the grid hands over as the rows after. */
    function edited(rows: ConditionGroup[], index: number, change: Partial<ConditionGroup>): ConditionGroup[] {
        return rows.map((candidate, at) => (at === index ? { ...candidate, ...change } : candidate));
    }

    /** The three moves of one rule, from one key base to another. */
    function movesBetween(from: string, to: string): { from: string; to: string }[] {
        return ['decision', 'prompt', 'manipulation'].map((step) => ({ from: `${from}:${step}`, to: `${to}:${step}` }));
    }

    /** The key base the dialog files `rows`' drawn rule `drawnIndex` under. */
    function baseOf(rows: ConditionGroup[], drawnIndex: number): string {
        return keysOf(rows)
            .get(`row-${drawnIndex}:decision`)!
            .replace(/:decision$/, '');
    }

    const table = (): ConditionGroup[] => [
        row({ group_name: 'Approve', route_code: 'approve', expression: 'score > 0.8', order: 1 }),
        row({ group_name: 'Reject', route_code: 'reject', expression: 'score < 0.2', order: 2 }),
    ];

    it('moves every step of a rule whose route code changed to the new code', () => {
        const before = table();
        const after = edited(before, 0, { route_code: 'Approved' });

        expect(explainKeyMovesForRuleEdit(before, after, 0)).toEqual(
            movesBetween('rule:route:approve', 'rule:route:approved')
        );
    });

    it('moves to the name when the route code is cleared', () => {
        const before = table();
        const after = edited(before, 0, { route_code: '' });

        expect(explainKeyMovesForRuleEdit(before, after, 0)).toEqual(
            movesBetween('rule:route:approve', 'rule:name:Approve')
        );
    });

    it('moves from the name to the route code once a rule without one is given one', () => {
        const before = edited(table(), 0, { route_code: null });
        const after = edited(before, 0, { route_code: 'approve' });

        expect(explainKeyMovesForRuleEdit(before, after, 0)).toEqual(
            movesBetween('rule:name:Approve', 'rule:route:approve')
        );
    });

    it('moves from the old name to the new one for a rule without a route code', () => {
        const before = edited(table(), 0, { route_code: '' });
        const after = edited(before, 0, { group_name: 'Accept' });

        expect(explainKeyMovesForRuleEdit(before, after, 0)).toEqual(
            movesBetween('rule:name:Approve', 'rule:name:Accept')
        );
    });

    it('moves nothing when the key holds: a rename under a route code, or a change of spacing only', () => {
        const before = table();

        expect(explainKeyMovesForRuleEdit(before, edited(before, 0, { group_name: 'Accept' }), 0)).toEqual([]);
        expect(explainKeyMovesForRuleEdit(before, edited(before, 0, { route_code: ' approve ' }), 0)).toEqual([]);
    });

    it('moves to and from content keys, matching the keys the dialog files the rule under', () => {
        // Both rules share the name; Approve's own code is what keeps it off a content key.
        const before = [
            row({ group_name: 'Same', route_code: 'a', expression: 'x > 1', order: 1 }),
            row({ group_name: 'Same', route_code: 'b', expression: 'x > 2', order: 2 }),
        ];
        const shared = edited(before, 0, { route_code: 'b' });

        const toContent = explainKeyMovesForRuleEdit(before, shared, 0);
        const fromContent = explainKeyMovesForRuleEdit(shared, before, 0);

        expect(baseOf(shared, 0)).toMatch(/^rule:content:/);
        expect(toContent).toEqual(movesBetween('rule:route:a', baseOf(shared, 0)));
        expect(fromContent).toEqual(movesBetween(baseOf(shared, 0), 'rule:route:a'));
    });

    it('moves only the edited rule, though the edit changes another rule’s key too', () => {
        const before = [
            row({ group_name: 'First', route_code: 'x', order: 1 }),
            row({ group_name: 'Second', route_code: 'x', order: 2 }),
        ];
        const after = edited(before, 0, { route_code: 'y' });

        // Second's code is now unique, so its key moves to it as well — and is left there.
        expect(baseOf(after, 1)).toBe('rule:route:x');
        expect(explainKeyMovesForRuleEdit(before, after, 0)).toEqual(movesBetween('rule:name:First', 'rule:route:y'));
    });

    it('works a hidden rule’s keys out as if it alone were shown, among the keys the store keeps for it', () => {
        const before = [
            row({ group_name: 'Spam', expression: 'a', dock_visible: false, order: 1 }),
            row({ group_name: 'Spam', expression: 'b', order: 2 }),
        ];
        const after = edited(before, 0, { group_name: 'Ham' });

        const moves = explainKeyMovesForRuleEdit(before, after, 0);

        // Shown beside the drawn Spam, the hidden one falls back to its content.
        expect(moves[0].from).toMatch(/^rule:content:.+:decision$/);
        expect(moves[0].to).toBe('rule:name:Ham:decision');
        expect(buildRetainedExplainStepKeys(input({ rows: before })).has(moves[0].from)).toBe(true);
        expect(buildRetainedExplainStepKeys(input({ rows: after })).has(moves[0].to)).toBe(true);
    });

    it('leaves a shared explanation with the identical rules still drawn with it', () => {
        const duplicate = (): ConditionGroup =>
            row({ group_name: 'Dup', route_code: 'x', expression: 'a > 1', order: 1 });
        const before = [duplicate(), duplicate(), duplicate()];
        const after = edited(before, 0, { route_code: 'y' });

        expect(explainKeyMovesForRuleEdit(before, after, 0)).toEqual([]);
    });

    it('takes a content key once no other drawn rule resolves to it', () => {
        const duplicate = (): ConditionGroup =>
            row({ group_name: 'Dup', route_code: 'x', expression: 'a > 1', order: 1 });
        const before = [duplicate(), duplicate()];
        const after = edited(before, 0, { route_code: 'y' });

        // The other duplicate's code is now unique, so it no longer files under the shared key.
        expect(explainKeyMovesForRuleEdit(before, after, 0)).toEqual(movesBetween(baseOf(before, 0), 'rule:route:y'));
    });

    it('does not write over the explanation of the identical rules it now duplicates', () => {
        const duplicate = (): ConditionGroup =>
            row({ group_name: 'Dup', route_code: 'x', expression: 'a > 1', order: 2 });
        const before = [
            row({ group_name: 'Dup', route_code: 'a', expression: 'a > 1', order: 1 }),
            duplicate(),
            duplicate(),
        ];
        const after = edited(before, 0, { route_code: 'x' });

        expect(baseOf(after, 0)).toBe(baseOf(after, 1));
        expect(explainKeyMovesForRuleEdit(before, after, 0)).toEqual([]);
    });

    it('moves nothing for a row that is not there', () => {
        expect(explainKeyMovesForRuleEdit(table(), table(), 5)).toEqual([]);
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
