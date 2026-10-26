import { PromptConfig } from '../../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { buildCdtDecisionTree } from './cdt-decision-tree.builder';
import { CdtDecisionTreeInput, CdtTreeBlockKind } from './cdt-decision-tree.model';
import {
    buildCdtExplainBlocks,
    buildCdtExplainTable,
    chunkExplainBlocks,
    resolveExplainLlmConfig,
} from './cdt-explain.payload';

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

/** The tree kinds that have an explainable step behind them. */
const EXPLAINABLE_KINDS: ReadonlySet<CdtTreeBlockKind> = new Set<CdtTreeBlockKind>([
    'pre-computation',
    'post-computation',
    'row-decision',
    'row-prompt',
    'row-manipulation',
]);

/**
 * Hidden rows and an order that differs from grid order, so an id derived from
 * the grid index instead of the drawn position names the wrong rule. The route is
 * resolved through a connection, so `anyRouted` holds and both post blocks are drawn.
 */
const MIXED = input({
    preCode: 'a = 1',
    postCode: 'b = 2',
    prompts: { classify: prompt() },
    rows: [
        row({ group_name: 'Late', expression: 'x > 3', order: 30, manipulation: 'late = True' }),
        row({ group_name: 'Hidden', expression: 'x > 0', order: 5, dock_visible: false, prompt_id: 'classify' }),
        row({ group_name: 'Early', expression: 'x > 1', order: 10, prompt_id: 'classify', route_code: 'approve' }),
        row({ group_name: '', expression: 'x > 2', order: 20 }),
    ],
    connections: [{ sourceNodeId: 'table', sourcePortId: 'table_decision-route-approve', targetNodeId: 'n2' }],
    nodes: [{ id: 'n2', node_name: 'Approver', backendId: 2 }],
});

describe('buildCdtExplainBlocks', () => {
    it('produces a block for exactly the explainable blocks the diagram draws', () => {
        const tree = buildCdtDecisionTree(MIXED);
        const drawn = tree.blocks.filter((block) => EXPLAINABLE_KINDS.has(block.kind)).map((block) => block.id);

        expect([...buildCdtExplainBlocks(MIXED).keys()].sort()).toEqual([...drawn].sort());
    });

    it('names each condition block after the rule the diagram draws under the same id', () => {
        const tree = buildCdtDecisionTree(MIXED);
        const blocks = buildCdtExplainBlocks(MIXED);

        const decisions = tree.blocks.filter((block) => block.kind === 'row-decision');
        expect(decisions.map((block) => block.title)).toEqual(['Early', 'Rule 2', 'Late']);

        for (const decision of decisions) {
            const block = blocks.get(decision.id);
            expect(block?.block).toBe('condition');
            expect(block && 'rule_name' in block ? block.rule_name : null).toBe(decision.title);
        }
    });

    it('carries each rule its own content after the hidden filter and the sort', () => {
        const blocks = buildCdtExplainBlocks(MIXED);

        expect(blocks.get('row-0:decision')).toMatchObject({
            expression: 'x > 1',
            route_code: 'approve',
            on_match: { prompt: 'classify', goes_to: 'Approver', sets_variables: false },
            on_no_match: null,
        });
        expect(blocks.get('row-2:decision')).toMatchObject({
            expression: 'x > 3',
            on_match: { prompt: null, goes_to: null, sets_variables: true },
            on_no_match: 'default_exit',
        });
        expect(blocks.get('row-2:manipulation')).toMatchObject({ rule_name: 'Late', assignments: 'late = True' });
        expect(blocks.has('row-0:prompt')).toBe(true);
        expect(blocks.has('row-3:decision')).toBe(false);
    });

    it('sends no prompt block for a prompt the table does not define', () => {
        const blocks = buildCdtExplainBlocks(input({ rows: [row({ group_name: 'R', prompt_id: 'missing' })] }));

        expect(blocks.has('row-0:prompt')).toBe(false);
        expect(blocks.get('row-0:decision')).toMatchObject({ on_match: { prompt: 'missing' } });
    });

    it('sends no computation block for whitespace-only code', () => {
        const blocks = buildCdtExplainBlocks(input({ preCode: '  ', postCode: '\n\t' }));

        expect(blocks.size).toBe(0);
    });
});

describe('node names in the explain request', () => {
    // Same-named, numbered nodes: the diagram tells them apart by number, the request must not.
    const nodes = [
        { id: 'n-approve', node_name: 'Approver', backendId: 2, nodeNumber: 4 },
        { id: 'n-escalate', node_name: 'Escalate', backendId: 3, nodeNumber: 5 },
        { id: 'n-fail', node_name: 'Fail', backendId: 4, nodeNumber: 6 },
    ];
    const routed = input({
        nodeNumber: 3,
        rows: [row({ group_name: 'Approve', route_code: 'approve', order: 1 })],
        connections: [
            { sourceNodeId: 'table', sourcePortId: 'table_decision-route-approve', targetNodeId: 'n-approve' },
        ],
        defaultNextNode: 'n-escalate',
        errorNextNode: 'n-fail',
        nodes,
    });

    it('sends the plain name of the node a rule goes to, without its number', () => {
        const block = buildCdtExplainBlocks(routed).get('row-0:decision');

        expect(block?.block === 'condition' && block.on_match.goes_to).toBe('Approver');
    });

    it('sends the plain names of the table, its default and its error node, without their numbers', () => {
        expect(buildCdtExplainTable(routed)).toMatchObject({
            node_name: 'Triage',
            default_next_node: 'Escalate',
            error_next_node: 'Fail',
        });
    });
});

describe('rule names', () => {
    it('numbers blank names by drawn position, matching the canvas', () => {
        const source = input({
            rows: [
                row({ group_name: '', order: 1 }),
                row({ group_name: 'Named', order: 2 }),
                row({ group_name: '  ', order: 3 }),
            ],
        });
        const blocks = buildCdtExplainBlocks(source);

        expect(blocks.get('row-0:decision')).toMatchObject({ rule_name: 'Rule 1' });
        expect(blocks.get('row-1:decision')).toMatchObject({ rule_name: 'Named' });
        expect(blocks.get('row-2:decision')).toMatchObject({ rule_name: 'Rule 3' });
        expect(buildCdtExplainTable(source).rules.map((rule) => rule.name)).toEqual(['Rule 1', 'Named', 'Rule 3']);
    });

    it('skips hidden rules when numbering a drawn one', () => {
        const source = input({
            rows: [row({ group_name: 'Off', order: 1, dock_visible: false }), row({ group_name: '', order: 2 })],
        });

        expect(buildCdtExplainBlocks(source).get('row-0:decision')).toMatchObject({ rule_name: 'Rule 1' });
    });

    it('lists hidden rules in the table, disabled, in order', () => {
        const table = buildCdtExplainTable(
            input({
                rows: [
                    row({ group_name: 'Second', order: 2 }),
                    row({ group_name: 'First', order: 1, dock_visible: false }),
                ],
            })
        );

        expect(table.rules).toEqual([
            { order: 1, name: 'First', enabled: false },
            { order: 2, name: 'Second', enabled: true },
        ]);
    });

    // A blank hidden rule takes its fallback from its position among *all* rules,
    // and a blank drawn rule from its position among the drawn ones, so the two can
    // land on the same name: here both are `Rule 1`, and the rules list the backend
    // quotes into the prompt cannot tell the disabled one from the live one.
    it('never gives a hidden rule the fallback name of a drawn one', () => {
        const table = buildCdtExplainTable(
            input({
                rows: [row({ group_name: '', order: 1, dock_visible: false }), row({ group_name: '', order: 2 })],
            })
        );
        const names = table.rules.map((rule) => rule.name);

        expect(new Set(names).size).toBe(names.length);
    });
});

describe('chunkExplainBlocks', () => {
    const manyRows = input({
        rows: Array.from({ length: 31 }, (_, index) =>
            row({ group_name: `R${index}`, order: index + 1, manipulation: `v${index} = ${index}` })
        ),
    });
    const blocks = [...buildCdtExplainBlocks(manyRows).values()];

    it('groups by block type before slicing, at 30 a request by default', () => {
        const chunks = chunkExplainBlocks(blocks);

        expect(chunks.map((chunk) => [chunk[0].block, chunk.length])).toEqual([
            ['condition', 30],
            ['condition', 1],
            ['manipulation', 30],
            ['manipulation', 1],
        ]);
        for (const chunk of chunks) {
            expect(new Set(chunk.map((block) => block.block)).size).toBe(1);
        }
    });

    it('keeps every block exactly once, in order within its type', () => {
        const chunks = chunkExplainBlocks(blocks, 7);
        const conditionIds = chunks.flat().filter((block) => block.block === 'condition');

        expect(chunks.flat()).toHaveLength(blocks.length);
        expect(conditionIds.map((block) => block.id)).toEqual(
            blocks.filter((block) => block.block === 'condition').map((block) => block.id)
        );
        expect(Math.max(...chunks.map((chunk) => chunk.length))).toBe(7);
    });

    it('returns no chunks for no blocks', () => {
        expect(chunkExplainBlocks([])).toEqual([]);
    });
});

describe('resolveExplainLlmConfig', () => {
    it('prefers the table default over any prompt model', () => {
        expect(resolveExplainLlmConfig(input({ defaultLlmConfig: 3, prompts: { p: prompt({ llm_config: 9 }) } }))).toBe(
            3
        );
    });

    it('keeps a default of 0 rather than treating it as unset', () => {
        expect(resolveExplainLlmConfig(input({ defaultLlmConfig: 0, prompts: { p: prompt({ llm_config: 9 }) } }))).toBe(
            0
        );
    });

    it('falls back to the first prompt that names a model', () => {
        expect(
            resolveExplainLlmConfig(
                input({ prompts: { none: prompt({ llm_config: null }), set: prompt({ llm_config: 9 }) } })
            )
        ).toBe(9);
    });

    it('is null when neither the table nor any prompt names a model', () => {
        expect(resolveExplainLlmConfig(input({ prompts: { p: prompt({ llm_config: null }) } }))).toBeNull();
        expect(resolveExplainLlmConfig(input())).toBeNull();
    });

    it('does not pick a workspace config the table never chose', () => {
        const withConfigs = input({
            llmConfigOptions: [{ id: 1, label: 'gpt', modelName: 'gpt-4o', providerIcon: 'openai', hasApiKey: true }],
        });

        expect(resolveExplainLlmConfig(withConfigs)).toBeNull();
    });
});
