import { NodeType } from '@shared/models';

import { portOffsetFromTop } from '../geometry/port-position';
import { CDT_INPUT_PORT_CENTER_Y_OFFSET, getClassificationTableVisualHeight } from '../helpers/node-size.util';
import { ClassificationDecisionTableNodeModel } from '../models/node.model';
import { buildLayoutGraph } from './layout-graph';
import { connect, makeNode, tableNode, tableRowRole, withPorts } from './testing/fixtures';

const CDT = NodeType.CLASSIFICATION_TABLE;

describe('buildLayoutGraph', () => {
    it('takes every port offset from portOffsetFromTop and the table height from its visual rows', () => {
        const table = tableNode('t', CDT, 3);
        const nodes = [makeNode('start', NodeType.START, { height: 60 }), table, makeNode('child', NodeType.PYTHON)];
        const connections = [
            connect('in', 'start', 'out', 't', 'table-in'),
            connect('row2', 't', tableRowRole(CDT, 2), 'child'),
        ];
        const ported = withPorts(nodes, connections);

        const { graph } = buildLayoutGraph(ported, connections);

        const rowPort = table.ports!.find((candidate) => candidate.role === tableRowRole(CDT, 2));
        const [input, row] = graph.edges;
        expect(row).toMatchObject({
            id: 'row2',
            sourceOffsetY: portOffsetFromTop(table, rowPort),
            targetOffsetY: 50,
            fromTableRow: true,
            sourceRow: 2,
        });
        expect(row.sourceOffsetY).toBe(210);
        expect(input).toMatchObject({ targetOffsetY: CDT_INPUT_PORT_CENTER_Y_OFFSET, fromTableRow: false });
        const conditionGroups = (table as ClassificationDecisionTableNodeModel).data.table.condition_groups;
        expect(graph.nodes.get('t')).toMatchObject({
            height: getClassificationTableVisualHeight(conditionGroups),
            inputOffsetY: CDT_INPUT_PORT_CENTER_Y_OFFSET,
            isTable: true,
        });
        expect(graph.nodes.get('start')!.isTrigger).toBe(true);
    });

    it('skips stale connections (missing node or port) without throwing', () => {
        const nodes = withPorts(
            [makeNode('a', NodeType.PYTHON), makeNode('b', NodeType.PYTHON)],
            [connect('ok', 'a', 'out', 'b')]
        );
        const connections = [
            connect('ok', 'a', 'out', 'b'),
            connect('no-node', 'a', 'out', 'ghost'),
            connect('no-port', 'a', 'missing-port', 'b'),
        ];

        const { graph, isolated } = buildLayoutGraph(nodes, connections);

        expect(graph.edges.map((edge) => edge.id)).toEqual(['ok']);
        expect(isolated).toEqual([]);
    });

    it('orders components trigger first, then larger, then by smallest id; singletons are isolated', () => {
        const connections = [
            connect('z1', 'z1', 'out', 'z2'),
            connect('z2', 'z2', 'out', 'z3'),
            connect('m1', 'm1', 'out', 'm2'),
            connect('m2', 'm2', 'out', 'm3'),
            connect('s', 'start', 'out', 'y'),
        ];
        const nodes = withPorts(
            [
                ...['z1', 'z2', 'z3', 'm1', 'm2', 'm3', 'y', 'lonely', 'alone'].map((id) =>
                    makeNode(id, NodeType.PYTHON)
                ),
                makeNode('start', NodeType.START),
                makeNode('note', NodeType.NOTE),
            ],
            connections
        );

        const { components, isolated } = buildLayoutGraph(nodes, connections);

        expect(components).toEqual([
            ['start', 'y'],
            ['m1', 'm2', 'm3'],
            ['z1', 'z2', 'z3'],
        ]);
        expect(isolated).toEqual(['alone', 'lonely']);
    });

    it('leaves self-loops out of the edges but marks the node', () => {
        const connections = [connect('loop', 'a', 'out', 'a'), connect('ab', 'a', 'out', 'b')];
        const nodes = withPorts([makeNode('a', NodeType.PYTHON), makeNode('b', NodeType.PYTHON)], connections);

        const { graph } = buildLayoutGraph(nodes, connections);

        expect(graph.edges.map((edge) => edge.id)).toEqual(['ab']);
        expect(graph.nodes.get('a')!.hasSelfLoop).toBe(true);
    });
});
