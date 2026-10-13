import { ConditionGroup } from '../../../../core/models/decision-table.model';
import {
    buildCdtDecisionTree,
    CdtRouteTargetSources,
    resolveRouteTargetId,
    routePortIdsWithTarget,
} from './cdt-decision-tree.builder';
import { CDT_TREE_COPY } from './cdt-decision-tree.constants';
import { CdtDecisionTreeInput, CdtTree, CdtTreeEdge, CdtTreeExitsLane } from './cdt-decision-tree.model';

function row(overrides: Partial<ConditionGroup>): ConditionGroup {
    return {
        group_name: 'Condition 1',
        group_type: 'complex',
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        ...overrides,
    };
}

function sources(overrides: Partial<CdtRouteTargetSources> = {}): CdtRouteTargetSources {
    return { nodeId: 'table', canvasRows: [], connections: [], ...overrides };
}

describe('resolveRouteTargetId', () => {
    it('reads the canvas row first, then the grid row', () => {
        const gridRow = row({ route_code: 'approve', next_node: 'grid-target' });

        expect(
            resolveRouteTargetId(
                gridRow,
                sources({ canvasRows: [row({ route_code: 'approve', next_node: 'canvas-target' })] })
            )
        ).toBe('canvas-target');
        expect(resolveRouteTargetId(gridRow, sources())).toBe('grid-target');
    });

    it('trusts an unwired canvas row over the grid row’s stale target', () => {
        const gridRow = row({ route_code: 'approve', next_node: 'grid-target' });
        const unwired = sources({ canvasRows: [row({ route_code: 'approve', next_node: null })] });

        expect(resolveRouteTargetId(gridRow, unwired)).toBeNull();
        expect(routePortIdsWithTarget([gridRow], unwired).size).toBe(0);
    });

    it('falls back to a connection on the route code port', () => {
        const connections = [
            { sourceNodeId: 'table', sourcePortId: 'table_decision-route-needs-review', targetNodeId: 'review' },
        ];

        expect(resolveRouteTargetId(row({ route_code: 'Needs Review' }), sources({ connections }))).toBe('review');
    });

    it('finds the connection of a saved route code with trailing whitespace on its own port', () => {
        const connections = [{ sourceNodeId: 'table', sourcePortId: 'table_decision-route-a-', targetNodeId: 'next' }];

        expect(resolveRouteTargetId(row({ route_code: 'A ' }), sources({ connections }))).toBe('next');
        expect(resolveRouteTargetId(row({ route_code: 'A' }), sources({ connections }))).toBeNull();
    });

    it('does not borrow the canvas target of a different port that trims to the same code', () => {
        const canvasRows = [row({ route_code: 'A ', next_node: 'next' })];

        expect(resolveRouteTargetId(row({ route_code: 'A' }), sources({ canvasRows }))).toBeNull();
    });

    it('is null without a route code or a target', () => {
        expect(resolveRouteTargetId(row({ route_code: '  ', next_node: 'x' }), sources())).toBeNull();
        expect(resolveRouteTargetId(row({ route_code: 'approve' }), sources())).toBeNull();
    });
});

describe('routePortIdsWithTarget', () => {
    it('collects the port ids that lead to a node, once each', () => {
        const rows = [
            row({ route_code: 'approve', next_node: 'a' }),
            row({ route_code: 'approve' }),
            row({ route_code: 'reject' }),
            row({ route_code: '' }),
        ];

        expect([...routePortIdsWithTarget(rows, sources())]).toEqual(['table_decision-route-approve']);
    });
});

// ---------------------------------------------------------------------------
// buildCdtDecisionTree
//
// Routing here is resolved only through `connections`, never `next_node`: which
// copy of `next_node` wins is being reworked separately and is not pinned here.
// ---------------------------------------------------------------------------

function treeInput(overrides: Partial<CdtDecisionTreeInput> = {}): CdtDecisionTreeInput {
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

/** A connection from the table's route port for `routeCode` to node `targetId`. */
function routeConnection(routeCode: string, targetId: string) {
    return {
        sourceNodeId: 'table',
        sourcePortId: `table_decision-route-${routeCode.toLowerCase().replace(/\s+/g, '-')}`,
        targetNodeId: targetId,
    };
}

const TARGET_NODES = [{ id: 'n-approve', node_name: 'Approver', backendId: 2 }];

function edgesFrom(tree: CdtTree, from: string): CdtTreeEdge[] {
    return tree.edges.filter((entry) => entry.from === from);
}

function blockIds(tree: CdtTree): string[] {
    return tree.blocks.map((entry) => entry.id);
}

function exitsLane(tree: CdtTree): CdtTreeExitsLane {
    const lane = tree.lanes.find((entry): entry is CdtTreeExitsLane => entry.kind === 'exits');
    if (!lane) throw new Error('no exits lane');
    return lane;
}

describe('buildCdtDecisionTree', () => {
    describe('with no rule to draw', () => {
        it('sends the head straight to the default exit and the error exit off its side', () => {
            const tree = buildCdtDecisionTree(treeInput());

            expect(tree.rowCount).toBe(0);
            expect(tree.hiddenRowCount).toBe(0);
            expect(blockIds(tree)).not.toContain('rules:region');
            expect(tree.lanes.some((lane) => lane.kind === 'region')).toBe(false);
            expect(edgesFrom(tree, 'spine:table-entered')).toEqual([
                expect.objectContaining({ to: 'exit:error:terminator', fromSide: 'right', kind: 'error' }),
                expect.objectContaining({
                    to: 'exit:default:terminator',
                    fromSide: 'bottom',
                    kind: 'default',
                    label: CDT_TREE_COPY.noRowMatched,
                }),
            ]);
        });

        it('leaves the last head block, not the entry, when there is pre-computation', () => {
            const tree = buildCdtDecisionTree(treeInput({ preCode: 'x = 1' }));

            expect(edgesFrom(tree, 'spine:pre-computation').map((entry) => entry.to)).toEqual([
                'exit:error:terminator',
                'exit:default:terminator',
            ]);
        });

        it('counts the hidden rules and draws none of them when every rule is hidden', () => {
            const tree = buildCdtDecisionTree(
                treeInput({
                    rows: [
                        row({ group_name: 'A', dock_visible: false, route_code: 'approve' }),
                        row({ group_name: 'B', dock_visible: false }),
                    ],
                    connections: [routeConnection('approve', 'n-approve')],
                    nodes: TARGET_NODES,
                })
            );

            expect(tree.rowCount).toBe(0);
            expect(tree.hiddenRowCount).toBe(2);
            expect(blockIds(tree).filter((id) => id.startsWith('row-'))).toEqual([]);
            expect(blockIds(tree)).not.toContain('exit:route:terminator');
            expect(edgesFrom(tree, 'spine:table-entered')).toContainEqual(
                expect.objectContaining({ to: 'exit:default:terminator', kind: 'default' })
            );
        });
    });

    describe('a rule with neither a prompt nor a manipulation', () => {
        it('keeps its yes and its fall-through apart when both lead to the default exit', () => {
            const tree = buildCdtDecisionTree(treeInput({ rows: [row({ group_name: 'Only' })] }));
            const fromRule = edgesFrom(tree, 'row-0:decision');

            expect(fromRule.map((entry) => [entry.kind, entry.to])).toEqual([
                ['default', 'exit:default:terminator'],
                ['yes', 'exit:default:terminator'],
            ]);
            expect(new Set(tree.edges.map((entry) => entry.id)).size).toBe(tree.edges.length);
        });

        it('keeps a continuing rule yes and no apart when both lead to the next rule', () => {
            const tree = buildCdtDecisionTree(
                treeInput({
                    rows: [
                        row({ group_name: 'First', continue_flag: true, order: 1 }),
                        row({ group_name: 'Second', order: 2 }),
                    ],
                })
            );

            expect(edgesFrom(tree, 'row-0:decision').map((entry) => [entry.kind, entry.to])).toEqual([
                ['no', 'row-1:decision'],
                ['yes', 'row-1:decision'],
            ]);
            expect(new Set(tree.edges.map((entry) => entry.id)).size).toBe(tree.edges.length);
        });
    });

    describe('Continue', () => {
        it('on the last rule leaves for the table default, not a rule that does not exist', () => {
            const tree = buildCdtDecisionTree(
                treeInput({ rows: [row({ group_name: 'Last', continue_flag: true, manipulation: 'x = 1' })] })
            );

            expect(edgesFrom(tree, 'row-0:manipulation')).toEqual([
                expect.objectContaining({ to: 'exit:default:terminator', kind: 'flow' }),
            ]);
            expect(tree.edges.some((entry) => entry.kind === 'continue')).toBe(false);
        });

        it('rejoins the next rule from the end of its chain when not last', () => {
            const tree = buildCdtDecisionTree(
                treeInput({
                    rows: [
                        row({ group_name: 'First', continue: true, manipulation: 'x = 1', order: 1 }),
                        row({ group_name: 'Second', order: 2 }),
                    ],
                })
            );

            expect(edgesFrom(tree, 'row-0:manipulation')).toEqual([
                expect.objectContaining({ to: 'row-1:decision', kind: 'continue' }),
            ]);
        });

        it('is ignored by a routed rule, which leaves through the route lane and says so', () => {
            const tree = buildCdtDecisionTree(
                treeInput({
                    rows: [
                        row({
                            group_name: 'Approve',
                            route_code: 'approve',
                            continue_flag: true,
                            manipulation: 'x = 1',
                            order: 1,
                        }),
                        row({ group_name: 'Next', order: 2 }),
                    ],
                    connections: [routeConnection('approve', 'n-approve')],
                    nodes: TARGET_NODES,
                })
            );
            const decision = tree.blocks.find((entry) => entry.id === 'row-0:decision');

            expect(decision?.target).toEqual({ state: 'node', label: 'Approver' });
            expect(decision?.note).toEqual({
                tag: CDT_TREE_COPY.continueIgnoredTag,
                tooltip: CDT_TREE_COPY.continueIgnoredTooltip,
            });
            expect(edgesFrom(tree, 'row-0:manipulation')).toEqual([
                expect.objectContaining({ to: 'exit:route:terminator', kind: 'flow' }),
            ]);
        });

        it('still applies to a route code wired to nothing, and the note says so', () => {
            const tree = buildCdtDecisionTree(
                treeInput({
                    rows: [
                        row({
                            group_name: 'Unwired',
                            route_code: 'nowhere',
                            continue_flag: true,
                            manipulation: 'x = 1',
                            order: 1,
                        }),
                        row({ group_name: 'Next', order: 2 }),
                    ],
                })
            );
            const decision = tree.blocks.find((entry) => entry.id === 'row-0:decision');

            expect(decision?.target).toEqual({ state: 'no-capture' });
            expect(decision?.note).toEqual({
                tag: CDT_TREE_COPY.continueAppliesTag,
                tooltip: CDT_TREE_COPY.continueAppliesTooltip,
            });
            expect(edgesFrom(tree, 'row-0:manipulation')).toEqual([
                expect.objectContaining({ to: 'row-1:decision', kind: 'continue' }),
            ]);
        });

        it('earns no note without a route code, or without Continue', () => {
            const tree = buildCdtDecisionTree(
                treeInput({
                    rows: [
                        row({ group_name: 'Plain continue', continue_flag: true, order: 1 }),
                        row({ group_name: 'Routed, stops', route_code: 'approve', order: 2 }),
                    ],
                    connections: [routeConnection('approve', 'n-approve')],
                    nodes: TARGET_NODES,
                })
            );

            expect(tree.blocks.filter((entry) => entry.kind === 'row-decision').map((entry) => entry.note)).toEqual([
                null,
                null,
            ]);
        });
    });

    describe('shared route codes', () => {
        it('chips every drawn rule that shares a trimmed route code, and no other', () => {
            const tree = buildCdtDecisionTree(
                treeInput({
                    rows: [
                        row({ group_name: 'A', route_code: 'refund', order: 1 }),
                        row({ group_name: 'B', route_code: 'refund ', order: 2 }),
                        row({ group_name: 'C', route_code: 'other', order: 3 }),
                        row({ group_name: 'Hidden', route_code: 'other', order: 4, dock_visible: false }),
                        row({ group_name: 'D', order: 5 }),
                    ],
                })
            );

            expect(tree.blocks.filter((entry) => entry.kind === 'row-decision').map((entry) => entry.chip)).toEqual([
                CDT_TREE_COPY.sharedRouteChip('refund'),
                CDT_TREE_COPY.sharedRouteChip('refund'),
                null,
                null,
            ]);
        });
    });

    describe('the route lane', () => {
        it('is not drawn when no rule routes to a node, even with post-computation', () => {
            const tree = buildCdtDecisionTree(
                treeInput({ postCode: 'y = 2', rows: [row({ group_name: 'Unwired', route_code: 'nowhere' })] })
            );

            expect(blockIds(tree)).not.toContain('exit:route:terminator');
            expect(blockIds(tree)).not.toContain('exit:route:post');
            expect(blockIds(tree).filter((id) => id.endsWith(':post'))).toEqual(['exit:default:post']);
            expect(exitsLane(tree).columns.map((column) => column.anchor)).toEqual(['spine', 'region']);
            expect(tree.groups.at(-1)?.blockIds).toEqual([
                'exit:default:post',
                'exit:default:terminator',
                'exit:error:terminator',
            ]);
        });

        it('is drawn, behind its own post-computation, as soon as one rule routes', () => {
            const tree = buildCdtDecisionTree(
                treeInput({
                    postCode: 'y = 2',
                    rows: [row({ group_name: 'Approve', route_code: 'approve' })],
                    connections: [routeConnection('approve', 'n-approve')],
                    nodes: TARGET_NODES,
                })
            );

            expect(exitsLane(tree).columns.at(-1)).toEqual({
                blockIds: ['exit:route:post', 'exit:route:terminator'],
                anchor: 'chain-corridor',
            });
            expect(edgesFrom(tree, 'row-0:decision')).toContainEqual(
                expect.objectContaining({ to: 'exit:route:post', kind: 'yes' })
            );
        });
    });
});
