import { PromptConfig } from '../../../../core/models/classification-decision-table.model';
import { ConditionGroup } from '../../../../core/models/decision-table.model';
import { buildCdtDecisionTree } from './cdt-decision-tree.builder';
import { CDT_TREE_REGION_PADDING, CDT_TREE_V_GAP } from './cdt-decision-tree.constants';
import { layoutCdtDecisionTree } from './cdt-decision-tree.layout';
import {
    CdtDecisionTreeInput,
    CdtTree,
    CdtTreeLayout,
    CdtTreePositionedBlock,
    inputConnectorId,
    outputConnectorId,
} from './cdt-decision-tree.model';

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

function prompt(): PromptConfig {
    return {
        prompt_text: 'Classify',
        llm_config: null,
        output_schema: null,
        result_variable: 'category',
        variable_mappings: {},
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

/** Three rules with chains of different lengths, one routed, pre and post code. */
const FULL = input({
    preCode: 'a = 1',
    postCode: 'b = 2',
    preInputMap: { score: 'variables.score' },
    prompts: { classify: prompt() },
    rows: [
        row({ group_name: 'Long', prompt_id: 'classify', manipulation: 'x = 1', route_code: 'approve', order: 1 }),
        row({ group_name: 'Short', manipulation: 'y = 2', order: 2 }),
        row({ group_name: 'Bare', order: 3 }),
    ],
    connections: [{ sourceNodeId: 'table', sourcePortId: 'table_decision-route-approve', targetNodeId: 'n2' }],
    nodes: [{ id: 'n2', node_name: 'Approver', backendId: 2 }],
});

function layout(source: CdtDecisionTreeInput): CdtTreeLayout {
    return layoutCdtDecisionTree(buildCdtDecisionTree(source));
}

function byId(result: CdtTreeLayout, id: string): CdtTreePositionedBlock {
    const found = result.blocks.find((entry) => entry.id === id);
    if (!found) throw new Error(`no block "${id}"`);
    return found;
}

const right = (block: CdtTreePositionedBlock): number => block.position.x + block.size.width;
const bottom = (block: CdtTreePositionedBlock): number => block.position.y + block.size.height;
const centreX = (block: CdtTreePositionedBlock): number => block.position.x + block.size.width / 2;

describe('layoutCdtDecisionTree', () => {
    it('lays out a table with no rules without throwing, and draws no region', () => {
        const result = layout(input());

        expect(result.rowCount).toBe(0);
        expect(result.blocks.map((entry) => entry.shape)).not.toContain('region');
        expect(byId(result, 'exit:default:terminator').position.y).toBeGreaterThan(
            bottom(byId(result, 'spine:table-entered'))
        );
    });

    it('keeps two exit columns apart when there are no rules to space them', () => {
        const result = layout(input());

        expect(byId(result, 'exit:error:terminator').position.x).toBeGreaterThan(
            right(byId(result, 'exit:default:terminator'))
        );
    });

    it('normalises to the origin and reports the bounds of everything drawn', () => {
        const result = layout(FULL);

        expect(Math.min(...result.blocks.map((entry) => entry.position.x))).toBe(0);
        expect(Math.min(...result.blocks.map((entry) => entry.position.y))).toBe(0);
        expect(result.bounds).toEqual({
            width: Math.max(...result.blocks.map(right)),
            height: Math.max(...result.blocks.map(bottom)),
        });
    });

    it('stacks the rules top to bottom in evaluation order, on one centre line', () => {
        const result = layout(FULL);
        const rules = ['row-0:decision', 'row-1:decision', 'row-2:decision'].map((id) => byId(result, id));

        for (let index = 1; index < rules.length; index++) {
            expect(rules[index].position.y).toBe(bottom(rules[index - 1]) + CDT_TREE_V_GAP);
            expect(centreX(rules[index])).toBe(centreX(rules[0]));
        }
    });

    it('ends every chain at the same x, so the exit strip past them stays clear', () => {
        const result = layout(FULL);

        expect(right(byId(result, 'row-1:manipulation'))).toBe(right(byId(result, 'row-0:manipulation')));
        expect(byId(result, 'row-0:prompt').position.x).toBeGreaterThan(right(byId(result, 'row-0:decision')));
    });

    it('centres a chain vertically on its rule', () => {
        const result = layout(FULL);
        const decision = byId(result, 'row-1:decision');
        const manipulation = byId(result, 'row-1:manipulation');

        expect(manipulation.position.y + manipulation.size.height / 2).toBe(
            decision.position.y + decision.size.height / 2
        );
    });

    it('wraps the rules and their chains in the region, with its padding', () => {
        const result = layout(FULL);
        const region = byId(result, 'rules:region');
        const covered = result.blocks.filter((entry) => entry.id.startsWith('row-'));

        expect(region.position.x).toBe(Math.min(...covered.map((entry) => entry.position.x)) - CDT_TREE_REGION_PADDING);
        expect(region.position.y).toBe(Math.min(...covered.map((entry) => entry.position.y)) - CDT_TREE_REGION_PADDING);
        expect(right(region)).toBe(Math.max(...covered.map(right)) + CDT_TREE_REGION_PADDING);
        expect(bottom(region)).toBe(Math.max(...covered.map(bottom)) + CDT_TREE_REGION_PADDING);
    });

    it('puts the exit row below everything else, the region included', () => {
        const result = layout(FULL);
        const exits = result.blocks.filter((entry) => entry.id.startsWith('exit:'));
        const rest = result.blocks.filter((entry) => !entry.id.startsWith('exit:'));

        expect(Math.min(...exits.map((entry) => entry.position.y))).toBeGreaterThan(Math.max(...rest.map(bottom)));
    });

    it('runs the exit columns left to right without overlap, the route lane last', () => {
        const result = layout(FULL);
        const defaultColumn = byId(result, 'exit:default:terminator');
        const errorColumn = byId(result, 'exit:error:terminator');
        const routeColumn = byId(result, 'exit:route:post');

        expect(errorColumn.position.x).toBeGreaterThan(right(defaultColumn));
        expect(routeColumn.position.x).toBeGreaterThan(right(errorColumn));
        expect(centreX(byId(result, 'exit:route:terminator'))).toBe(centreX(routeColumn));
    });

    it('gives every edge its own connector at each end', () => {
        const result = layout(FULL);
        const outIds = result.blocks.flatMap((entry) => entry.outPorts.map((port) => port.id));
        const inIds = result.blocks.flatMap((entry) => entry.inPorts.map((port) => port.id));

        expect(outIds.sort()).toEqual(result.edges.map((entry) => outputConnectorId(entry.id)).sort());
        expect(inIds.sort()).toEqual(result.edges.map((entry) => inputConnectorId(entry.id)).sort());
        expect(new Set(outIds).size).toBe(outIds.length);
    });

    it('is deterministic', () => {
        expect(layout(FULL)).toEqual(layout(FULL));
    });

    it('names the block when a lane points at one that was never built', () => {
        const tree = buildCdtDecisionTree(FULL);
        const broken: CdtTree = {
            ...tree,
            lanes: tree.lanes.map((lane) =>
                lane.kind === 'spine' ? { ...lane, blockIds: [...lane.blockIds, 'ghost'] } : lane
            ),
        };

        expect(() => layoutCdtDecisionTree(broken)).toThrow(/"ghost"/);
    });
});
