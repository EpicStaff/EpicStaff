import { IPoint } from '@foblex/2d';
import { NodeType } from '@shared/models';

import { getClassificationTableVisualHeight, getDecisionTableVisualHeight } from '../../helpers/node-size.util';
import { ConnectionModel } from '../../models/connection.model';
import { NodeModel } from '../../models/node.model';
import { CustomPortId, ViewPort } from '../../models/port.model';
import { findBackEdges } from '../cycles';
import { assignLayers } from '../layering';
import { buildLayoutGraph } from '../layout-graph';
import { LayeredGraph, splitLongEdges } from '../long-edges';

/** Test-only builders for the layout and router specs. Nothing here is imported by app code. */

export interface FlowFixture {
    nodes: NodeModel[];
    connections: ConnectionModel[];
}

type RowBasedTableType = NodeType.TABLE | NodeType.CLASSIFICATION_TABLE;

export function port(nodeId: string, role: string, position: ViewPort['position']): ViewPort {
    return {
        id: `${nodeId}_${role}` as CustomPortId,
        port_type: position === 'left' ? 'input' : 'output',
        role,
        multiple: true,
        label: role,
        allowedConnections: [],
        position,
    };
}

export function makeNode(
    id: string,
    type: NodeType,
    options: { width?: number; height?: number; position?: IPoint; ports?: ViewPort[]; data?: unknown } = {}
): NodeModel {
    return {
        id,
        type,
        node_name: id,
        position: options.position ?? { x: 0, y: 0 },
        size: { width: options.width ?? 330, height: options.height ?? 100 },
        ports: options.ports ?? [],
        data: options.data ?? null,
    } as unknown as NodeModel;
}

export function connect(
    id: string,
    sourceId: string,
    sourceRole: string,
    targetId: string,
    targetRole = 'input'
): ConnectionModel {
    return {
        id,
        category: 'default',
        sourceNodeId: sourceId,
        targetNodeId: targetId,
        sourcePortId: `${sourceId}_${sourceRole}` as CustomPortId,
        targetPortId: `${targetId}_${targetRole}` as CustomPortId,
        behavior: 'floating',
        type: 'segment',
        data: null,
    };
}

export function tableRowRole(type: RowBasedTableType, rowIndex: number): string {
    return (type === NodeType.TABLE ? 'decision-out-' : 'decision-route-') + `row-${rowIndex}`;
}

/**
 * A row-based table with rows `row-0..row-N-1`, its `table-in` port and one output port per row.
 * The height is the rendered (visual) height, as `normalizeTableNodeSize` sets it in the app.
 */
export function tableNode(id: string, type: RowBasedTableType, rowCount: number, position?: IPoint): NodeModel {
    const rowNames = Array.from({ length: rowCount }, (_, rowIndex) => `row-${rowIndex}`);
    const conditionGroups = rowNames.map((name, order) => ({
        group_name: name,
        group_type: 'simple' as const,
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        valid: true,
        order,
        route_code: name,
        dock_visible: true,
    }));
    const height =
        type === NodeType.TABLE
            ? getDecisionTableVisualHeight(conditionGroups)
            : getClassificationTableVisualHeight(conditionGroups);
    return makeNode(id, type, {
        height,
        position,
        ports: [
            port(id, 'table-in', 'left'),
            ...rowNames.map((_, rowIndex) => port(id, tableRowRole(type, rowIndex), 'right')),
        ],
        data: { name: id, table: { condition_groups: conditionGroups } },
    });
}

/** Registers every port a connection references and the node lacks: sources on the right, targets on the left. */
export function withPorts(nodes: NodeModel[], connections: ConnectionModel[]): NodeModel[] {
    return nodes.map((node) => {
        const ports = [...(node.ports ?? [])];
        const addPort = (portId: string, position: ViewPort['position']): void => {
            if (ports.some((existing) => existing.id === portId)) return;
            ports.push(port(node.id, portId.slice(node.id.length + 1), position));
        };
        for (const connection of connections) {
            if (connection.sourceNodeId === node.id) addPort(connection.sourcePortId, 'right');
            if (connection.targetNodeId === node.id) addPort(connection.targetPortId, 'left');
        }
        return { ...node, ports };
    });
}

/** Moves every node that has an entry in `positions`; the rest keep theirs. */
export function withPositions(nodes: NodeModel[], positions: Map<string, IPoint>): NodeModel[] {
    return nodes.map((node) => {
        const position = positions.get(node.id);
        return position ? { ...node, position: { x: position.x, y: position.y } } : node;
    });
}

function fixture(nodes: NodeModel[], connections: ConnectionModel[]): FlowFixture {
    return { nodes: withPorts(nodes, connections), connections };
}

// A node captured from the editor (flowService state), trimmed to the geometry.
interface DumpedNode {
    id: string;
    type: NodeType;
    name: string;
    position: IPoint;
    size: { width: number; height: number };
    ports: string[]; // `role:position`, or `role:position:idSuffix` when the port id isn't `<nodeId>_<role>`
    groups?: {
        group_name: string;
        order: number;
        dock_visible?: boolean;
        route_code?: string | null;
        valid?: boolean;
    }[];
}

// Fixture `flow8`, a flow captured from the editor and trimmed to the geometry: python code,
// prompts and backend records are dropped. Positions are the ones on the canvas at capture time.
// The captured ids and names are replaced: an id is `<fixture>-<NN>-<kind><number>` (`f9-12-cdt14` is
// CDT#14), NN numbered in the sort order of the captured ids, so every tie broken by id breaks the same way.
const FLOW8_NODES: DumpedNode[] = [
    {
        id: 'f8-01-start',
        type: NodeType.START,
        name: '__start__',
        position: { x: 0, y: 0 },
        size: { width: 125, height: 60 },
        ports: ['start-start:right'],
    },
    {
        id: 'f8-02-py9',
        type: NodeType.PYTHON,
        name: 'Python-Node #9',
        position: { x: 2240, y: 60 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f8-06-py3',
        type: NodeType.PYTHON,
        name: 'Python-Node #3',
        position: { x: 1160, y: 0 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f8-05-py7',
        type: NodeType.PYTHON,
        name: 'Python-Node #7',
        position: { x: 1580, y: 240 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f8-03-py8',
        type: NodeType.PYTHON,
        name: 'Python-Node #8',
        position: { x: 1580, y: 300 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f8-04-py10',
        type: NodeType.PYTHON,
        name: 'Python-Node #10',
        position: { x: 240, y: 0 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f8-10-file5',
        type: NodeType.FILE_EXTRACTOR,
        name: 'File Extractor #5',
        position: { x: 1160, y: 120 },
        size: { width: 330, height: 60 },
        ports: ['file-extractor-in:left', 'file-extractor-out:right'],
    },
    {
        id: 'f8-08-audio4',
        type: NodeType.AUDIO_TO_TEXT,
        name: 'Audio-to-text #4',
        position: { x: 1160, y: 60 },
        size: { width: 330, height: 60 },
        ports: ['audio-to-text-in:left', 'audio-to-text-out:right'],
    },
    {
        id: 'f8-09-end',
        type: NodeType.END,
        name: '__end_node__',
        position: { x: 2360, y: 420 },
        size: { width: 330, height: 60 },
        ports: ['end-in:left'],
    },
    {
        id: 'f8-11-cdt2',
        type: NodeType.CLASSIFICATION_TABLE,
        name: 'Classification Decision Table #2',
        position: { x: 640, y: -60 },
        size: { width: 330, height: 360 },
        ports: [
            'table-in:left',
            'decision-route-row1:right',
            'decision-route-row2:right',
            'decision-route-row3:right',
            'decision-default:right',
            'decision-error:right',
        ],
        groups: [
            { group_name: 'Condition 1', order: 1, dock_visible: true, route_code: 'row1' },
            { group_name: 'Condition 2', order: 2, dock_visible: true, route_code: 'row2' },
            { group_name: 'Condition 3', order: 3, dock_visible: true, route_code: 'row3' },
        ],
    },
    {
        id: 'f8-07-cdt6',
        type: NodeType.CLASSIFICATION_TABLE,
        name: 'Classification Decision Table #6',
        position: { x: 1580, y: 0 },
        size: { width: 330, height: 240 },
        ports: ['table-in:left', 'decision-route-route_1:right', 'decision-default:right', 'decision-error:right'],
        groups: [{ group_name: 'Condition 1', order: 1, dock_visible: true, route_code: 'route_1' }],
    },
];

// [sourceNodeId, sourceRole, targetNodeId, targetRole]; the connection id is `sourcePortId+targetPortId`,
// as the editor builds it.
const FLOW8_CONNECTIONS: [string, string, string, string][] = [
    ['f8-06-py3', 'python-out', 'f8-07-cdt6', 'table-in'],
    ['f8-08-audio4', 'audio-to-text-out', 'f8-05-py7', 'python-in'],
    ['f8-10-file5', 'file-extractor-out', 'f8-03-py8', 'python-in'],
    ['f8-01-start', 'start-start', 'f8-04-py10', 'python-in'],
    ['f8-04-py10', 'python-out', 'f8-11-cdt2', 'table-in'],
    ['f8-11-cdt2', 'decision-error', 'f8-09-end', 'end-in'],
    ['f8-11-cdt2', 'decision-route-row1', 'f8-06-py3', 'python-in'],
    ['f8-11-cdt2', 'decision-route-row2', 'f8-08-audio4', 'audio-to-text-in'],
    ['f8-11-cdt2', 'decision-route-row3', 'f8-10-file5', 'file-extractor-in'],
    ['f8-07-cdt6', 'decision-default', 'f8-09-end', 'end-in'],
    ['f8-07-cdt6', 'decision-error', 'f8-09-end', 'end-in'],
    ['f8-07-cdt6', 'decision-route-route_1', 'f8-02-py9', 'python-in'],
];

export function flow8(): FlowFixture {
    return fromDump(FLOW8_NODES, FLOW8_CONNECTIONS);
}

// Builds a captured flow's nodes and connections; the connection id is `sourcePortId+targetPortId`,
// as the editor builds it.
function fromDump(dumpedNodes: DumpedNode[], dumpedConnections: [string, string, string, string][]): FlowFixture {
    const nodes = dumpedNodes.map((data) => {
        const ports = data.ports.map((spec) => {
            const [role, position, idSuffix] = spec.split(':') as [string, ViewPort['position'], string?];
            return { ...port(data.id, role, position), id: `${data.id}_${idSuffix ?? role}` as CustomPortId };
        });
        const node = makeNode(data.id, data.type, {
            width: data.size.width,
            height: data.size.height,
            position: data.position,
            ports,
            data: data.groups ? { name: data.name, table: { condition_groups: data.groups } } : { name: data.name },
        });
        return { ...node, node_name: data.name };
    });
    const connections = dumpedConnections.map(([sourceId, sourceRole, targetId, targetRole]) =>
        connect(`${sourceId}_${sourceRole}+${targetId}_${targetRole}`, sourceId, sourceRole, targetId, targetRole)
    );
    return { nodes, connections };
}

// Three synthetic flow-6 shapes. A table target uses its real `table-in` port and tables get their
// visual height, so the router sees the geometry the app renders.

export function flow6PortAlignedTable(): FlowFixture {
    const nodes = [
        makeNode('s1', NodeType.START, { height: 60 }),
        makeNode('s2', NodeType.START, { height: 60 }),
        makeNode('p', NodeType.AGENT, { height: 60 }),
        makeNode('w', NodeType.AGENT, { height: 700 }),
        tableNode('T', NodeType.CLASSIFICATION_TABLE, 2),
        tableNode('cdt', NodeType.CLASSIFICATION_TABLE, 5),
        makeNode('py1', NodeType.PYTHON, { height: 60 }),
        makeNode('py2', NodeType.PYTHON, { height: 60 }),
    ];
    const connections = [
        connect('c1', 's1', 'o1', 'p'),
        connect('c2', 's1', 'o2', 'w'),
        connect('c3', 's2', 'o1', 'p'),
        connect('c4', 's2', 'o2', 'T', 'table-in'),
        connect('c5', 'p', 'o1', 'cdt', 'table-in'),
        connect('c6', 'T', tableRowRole(NodeType.CLASSIFICATION_TABLE, 0), 'py1'),
        connect('c7', 'T', tableRowRole(NodeType.CLASSIFICATION_TABLE, 1), 'py2'),
    ];
    return fixture(nodes, connections);
}

export function flow6RowPinnedChildren(): FlowFixture {
    const nodes = [
        makeNode('s1', NodeType.START, { height: 60 }),
        makeNode('s2', NodeType.START, { height: 60 }),
        makeNode('W', NodeType.AGENT, { height: 700 }),
        makeNode('p', NodeType.AGENT, { height: 60 }),
        makeNode('u', NodeType.AGENT, { height: 60 }),
        tableNode('cdt', NodeType.CLASSIFICATION_TABLE, 2),
        makeNode('v', NodeType.AGENT, { height: 60 }),
        makeNode('py1', NodeType.PYTHON, { height: 60 }),
        makeNode('py2', NodeType.PYTHON, { height: 60 }),
        makeNode('big', NodeType.AGENT, { height: 360 }),
        makeNode('small', NodeType.AGENT, { height: 60 }),
    ];
    const connections = [
        connect('c1', 's1', 'o1', 'p'),
        connect('c2', 's1', 'o2', 'W'),
        connect('c3', 's2', 'o1', 'p'),
        connect('c4', 's2', 'o2', 'u'),
        connect('c5', 'p', 'o1', 'cdt', 'table-in'),
        connect('c6', 'u', 'o1', 'v'),
        connect('c7', 'cdt', tableRowRole(NodeType.CLASSIFICATION_TABLE, 0), 'py1'),
        connect('c8', 'cdt', tableRowRole(NodeType.CLASSIFICATION_TABLE, 1), 'py2'),
        connect('c9', 'v', 'o1', 'big'),
        connect('c10', 'v', 'o2', 'small'),
    ];
    return fixture(nodes, connections);
}

export function flow6RelocatesPinned(): FlowFixture {
    const nodes = [
        makeNode('start', NodeType.START),
        tableNode('cdt8', NodeType.CLASSIFICATION_TABLE, 4),
        makeNode('pn12', NodeType.PYTHON, { height: 60 }),
        makeNode('pn5', NodeType.PYTHON, { height: 60 }),
        makeNode('pn11', NodeType.PYTHON, { height: 60 }),
        tableNode('cdt10', NodeType.CLASSIFICATION_TABLE, 5),
        tableNode('tableY', NodeType.CLASSIFICATION_TABLE, 3),
        makeNode('python13', NodeType.PYTHON, { height: 60 }),
    ];
    const connections = [
        connect('c1', 'start', 'out1', 'cdt8', 'table-in'),
        connect('c2', 'cdt8', tableRowRole(NodeType.CLASSIFICATION_TABLE, 0), 'pn12'),
        connect('c3', 'cdt8', tableRowRole(NodeType.CLASSIFICATION_TABLE, 1), 'pn5'),
        connect('c4', 'cdt8', tableRowRole(NodeType.CLASSIFICATION_TABLE, 2), 'pn11'),
        connect('c5', 'cdt8', tableRowRole(NodeType.CLASSIFICATION_TABLE, 3), 'cdt10', 'table-in'),
        connect('c6', 'start', 'out2', 'tableY', 'table-in'),
        connect('c7', 'tableY', tableRowRole(NodeType.CLASSIFICATION_TABLE, 0), 'python13'),
    ];
    return fixture(nodes, connections);
}

/**
 * Py#14 → Py#15 stacked in one column: the wire must return left through the gap.
 * The default top (120) leaves a 60-px gap between the node boxes, over the 20-px stacked-gap
 * threshold (measured between the unpadded boxes; the padded boxes are 40 px apart).
 */
export function stackedPair(targetTop = 120): FlowFixture {
    const nodes = [
        makeNode('py14', NodeType.PYTHON, { height: 60, position: { x: 0, y: 0 } }),
        makeNode('py15', NodeType.PYTHON, { height: 60, position: { x: 0, y: targetTop } }),
    ];
    return fixture(nodes, [connect('c14-15', 'py14', 'python-out', 'py15', 'python-in')]);
}

export function selfLoop(): FlowFixture {
    const nodes = [
        makeNode('start', NodeType.START, { width: 125, height: 60, position: { x: 0, y: 0 } }),
        makeNode('loop', NodeType.PYTHON, { height: 60, position: { x: 320, y: 0 } }),
    ];
    const connections = [connect('c1', 'start', 'out', 'loop'), connect('c2', 'loop', 'out', 'loop')];
    return fixture(nodes, connections);
}

export function threeCycle(): FlowFixture {
    const nodes = [
        makeNode('start', NodeType.START, { width: 125, height: 60, position: { x: 0, y: 0 } }),
        makeNode('a', NodeType.AGENT, { height: 60, position: { x: 320, y: 0 } }),
        makeNode('b', NodeType.AGENT, { height: 60, position: { x: 840, y: 0 } }),
        makeNode('c', NodeType.AGENT, { height: 60, position: { x: 1360, y: 0 } }),
    ];
    const connections = [
        connect('c1', 'start', 'out', 'a'),
        connect('c2', 'a', 'out', 'b'),
        connect('c3', 'b', 'out', 'c'),
        connect('c4', 'c', 'out', 'a'),
    ];
    return fixture(nodes, connections);
}

export function twoComponents(): FlowFixture {
    const nodes = [
        makeNode('start', NodeType.START, { width: 125, height: 60, position: { x: 0, y: 0 } }),
        makeNode('a', NodeType.AGENT, { height: 60, position: { x: 320, y: 0 } }),
        makeNode('b', NodeType.AGENT, { height: 60, position: { x: 840, y: 0 } }),
        makeNode('hook', NodeType.WEBHOOK_TRIGGER, { height: 60, position: { x: 0, y: 400 } }),
        makeNode('c', NodeType.AGENT, { height: 60, position: { x: 520, y: 400 } }),
        makeNode('d', NodeType.AGENT, { height: 60, position: { x: 1040, y: 400 } }),
    ];
    const connections = [
        connect('c1', 'start', 'out', 'a'),
        connect('c2', 'a', 'out', 'b'),
        connect('c3', 'hook', 'out', 'c'),
        connect('c4', 'c', 'out', 'd'),
    ];
    return fixture(nodes, connections);
}

export function isolatedNodes(): FlowFixture {
    const nodes = [
        makeNode('start', NodeType.START, { width: 125, height: 60, position: { x: 0, y: 0 } }),
        makeNode('a', NodeType.AGENT, { height: 60, position: { x: 320, y: 0 } }),
        makeNode('lonely1', NodeType.AGENT, { height: 60, position: { x: 0, y: 300 } }),
        makeNode('lonely2', NodeType.PYTHON, { height: 60, position: { x: 520, y: 300 } }),
    ];
    return fixture(nodes, [connect('c1', 'start', 'out', 'a')]);
}

// Fixture `liveFlow6`, another captured flow trimmed the same way. Start → Py7 → CDT11,
// whose rows feed Py1/Py2/Py3 and whose Default and Error both feed End; Py1 → File Extractor 8,
// Py2 → Audio 9, Py3 → DT10 (rows → Py4, Py5, Default → Py6). Three loops: Py4 → DT10, Py6 → DT10
// and Py5 → Py7. (`flow6*` above are the synthetic shapes, hence `liveFlow6`.)
const LIVE_FLOW6_NODES: DumpedNode[] = [
    {
        id: 'f6-03-start',
        type: NodeType.START,
        name: '__start__',
        position: { x: -580, y: 320 },
        size: { width: 125, height: 60 },
        ports: ['start-start:right'],
    },
    {
        id: 'f6-02-py6',
        type: NodeType.PYTHON,
        name: 'Python-Node #6',
        position: { x: 1860, y: 720 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f6-07-py7',
        type: NodeType.PYTHON,
        name: 'Python-Node #7',
        position: { x: -300, y: 360 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f6-11-py1',
        type: NodeType.PYTHON,
        name: 'Python-Node #1',
        position: { x: 600, y: 260 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f6-04-py2',
        type: NodeType.PYTHON,
        name: 'Python-Node #2',
        position: { x: 600, y: 360 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f6-08-py3',
        type: NodeType.PYTHON,
        name: 'Python-Node #3',
        position: { x: 620, y: 460 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f6-10-py4',
        type: NodeType.PYTHON,
        name: 'Python-Node #4',
        position: { x: 1820, y: 480 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f6-06-py5',
        type: NodeType.PYTHON,
        name: 'Python-Node #5',
        position: { x: 1880, y: 600 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f6-12-file8',
        type: NodeType.FILE_EXTRACTOR,
        name: 'File Extractor #8',
        position: { x: 1340, y: 240 },
        size: { width: 330, height: 60 },
        ports: ['file-extractor-in:left', 'file-extractor-out:right'],
    },
    {
        id: 'f6-01-audio9',
        type: NodeType.AUDIO_TO_TEXT,
        name: 'Audio-to-text #9',
        position: { x: 1420, y: 340 },
        size: { width: 330, height: 60 },
        ports: ['audio-to-text-in:left', 'audio-to-text-out:right'],
    },
    {
        id: 'f6-09-end',
        type: NodeType.END,
        name: '__end_node__',
        position: { x: 940, y: 840 },
        size: { width: 330, height: 60 },
        ports: ['end-in:left'],
    },
    {
        id: 'f6-13-dt10',
        type: NodeType.TABLE,
        name: 'Decision-Table #10',
        position: { x: 1260, y: 460 },
        size: { width: 330, height: 300 },
        ports: [
            'table-in:left',
            'decision-out-Condition 1:right:decision-out-condition-1',
            'decision-out-Condition 2:right:decision-out-condition-2',
            'decision-default:right',
            'decision-error:right',
        ],
        groups: [
            { group_name: 'Condition 1', order: 1, valid: true },
            { group_name: 'Condition 2', order: 2, valid: true },
        ],
    },
    {
        id: 'f6-05-cdt11',
        type: NodeType.CLASSIFICATION_TABLE,
        name: 'Classification Decision Table #11',
        position: { x: 100, y: 260 },
        size: { width: 330, height: 360 },
        ports: [
            'table-in:left',
            'decision-route-row1:right',
            'decision-route-row2:right',
            'decision-route-row3:right',
            'decision-default:right',
            'decision-error:right',
        ],
        groups: [
            { group_name: 'Condition 1', order: 1, dock_visible: true, route_code: 'row1' },
            { group_name: 'Condition 2', order: 2, dock_visible: true, route_code: 'row2' },
            { group_name: 'Condition 3', order: 3, dock_visible: true, route_code: 'row3' },
        ],
    },
];

const LIVE_FLOW6_CONNECTIONS: [string, string, string, string][] = [
    ['f6-11-py1', 'python-out', 'f6-12-file8', 'file-extractor-in'],
    ['f6-04-py2', 'python-out', 'f6-01-audio9', 'audio-to-text-in'],
    ['f6-08-py3', 'python-out', 'f6-13-dt10', 'table-in'],
    ['f6-03-start', 'start-start', 'f6-07-py7', 'python-in'],
    ['f6-07-py7', 'python-out', 'f6-05-cdt11', 'table-in'],
    ['f6-06-py5', 'python-out', 'f6-07-py7', 'python-in'],
    ['f6-02-py6', 'python-out', 'f6-13-dt10', 'table-in'],
    ['f6-10-py4', 'python-out', 'f6-13-dt10', 'table-in'],
    ['f6-13-dt10', 'decision-out-condition-1', 'f6-10-py4', 'python-in'],
    ['f6-13-dt10', 'decision-out-condition-2', 'f6-06-py5', 'python-in'],
    ['f6-13-dt10', 'decision-default', 'f6-02-py6', 'python-in'],
    ['f6-05-cdt11', 'decision-default', 'f6-09-end', 'end-in'],
    ['f6-05-cdt11', 'decision-error', 'f6-09-end', 'end-in'],
    ['f6-05-cdt11', 'decision-route-row1', 'f6-11-py1', 'python-in'],
    ['f6-05-cdt11', 'decision-route-row2', 'f6-04-py2', 'python-in'],
    ['f6-05-cdt11', 'decision-route-row3', 'f6-08-py3', 'python-in'],
];

export function liveFlow6(): FlowFixture {
    return fromDump(LIVE_FLOW6_NODES, LIVE_FLOW6_CONNECTIONS);
}

// Fixture `flow9`, another captured flow trimmed the same way: a DAG. CDT#14's rows feed 7
// children, several of them from more than one row (Py#8 from route_08, route_01 and Error; Py#4
// from route_06, route_07 and route_11; Py#7 from route_03 and route_02); six of them merge into
// Py#3 → DT#13 → DT#12 → Task#17 → Py#10 → Py#2 → Py#5 → End, and Py#1 skips to Py#5. The
// `route_04` group has no route_code, so it renders no row. The row names are numbered in the sort
// order of the captured ones, not in row order: CDT#14's row 0 is route_10, DT#12's first row Row 2.
const FLOW9_NODES: DumpedNode[] = [
    {
        id: 'f9-04-start',
        type: NodeType.START,
        name: '__start__',
        position: { x: 140, y: 720 },
        size: { width: 330, height: 60 },
        ports: ['start-start:right'],
    },
    {
        id: 'f9-07-py1',
        type: NodeType.PYTHON,
        name: 'Python-Node #1',
        position: { x: 2180, y: 110 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f9-16-py2',
        type: NodeType.PYTHON,
        name: 'Python-Node #2',
        position: { x: 5740, y: 740 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f9-06-py3',
        type: NodeType.PYTHON,
        name: 'Python-Node #3',
        position: { x: 2880, y: 710 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f9-01-py4',
        type: NodeType.PYTHON,
        name: 'Python-Node #4',
        position: { x: 2180, y: 540 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f9-13-py5',
        type: NodeType.PYTHON,
        name: 'Python-Node #5',
        position: { x: 6320, y: 100 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f9-08-py6',
        type: NodeType.PYTHON,
        name: 'Python-Node #6',
        position: { x: 1020, y: 720 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f9-19-py7',
        type: NodeType.PYTHON,
        name: 'Python-Node #7',
        position: { x: 2180, y: 640 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f9-05-py8',
        type: NodeType.PYTHON,
        name: 'Python-Node #8',
        position: { x: 2180, y: 740 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f9-03-py9',
        type: NodeType.PYTHON,
        name: 'Python-Node #9',
        position: { x: 2180, y: 290 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f9-09-py10',
        type: NodeType.PYTHON,
        name: 'Python-Node #10',
        position: { x: 5280, y: 740 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f9-18-py11',
        type: NodeType.PYTHON,
        name: 'Python-Node #11',
        position: { x: 580, y: 720 },
        size: { width: 330, height: 60 },
        ports: ['python-in:left', 'python-out:right'],
    },
    {
        id: 'f9-11-task17',
        type: NodeType.TASK,
        name: 'Task #17',
        position: { x: 4820, y: 740 },
        size: { width: 330, height: 60 },
        ports: ['task-in:left', 'task-out:right'],
    },
    {
        id: 'f9-17-task18',
        type: NodeType.TASK,
        name: 'Task #18',
        position: { x: 4000, y: 620 },
        size: { width: 330, height: 60 },
        ports: ['task-in:left', 'task-out:right'],
    },
    {
        id: 'f9-10-agent15',
        type: NodeType.AGENT,
        name: 'Agent #15',
        position: { x: 2180, y: 1010 },
        size: { width: 330, height: 60 },
        ports: ['agent-in:left', 'agent-out:right'],
    },
    {
        id: 'f9-15-agent16',
        type: NodeType.AGENT,
        name: 'Agent #16',
        position: { x: 2180, y: 830 },
        size: { width: 330, height: 60 },
        ports: ['agent-in:left', 'agent-out:right'],
    },
    {
        id: 'f9-20-end',
        type: NodeType.END,
        name: '__end_node__',
        position: { x: 7060, y: 100 },
        size: { width: 330, height: 60 },
        ports: ['end-in:left'],
    },
    {
        id: 'f9-02-dt12',
        type: NodeType.TABLE,
        name: 'Decision-Table #12',
        position: { x: 4420, y: 740 },
        size: { width: 330, height: 300 },
        ports: [
            'table-in:left',
            'decision-out-Row 2:right:decision-out-row-2',
            'decision-out-Row 1:right:decision-out-row-1',
            'decision-default:right',
            'decision-error:right',
        ],
        groups: [
            { group_name: 'Row 2', order: 1, valid: true },
            { group_name: 'Row 1', order: 2, valid: true },
        ],
    },
    {
        id: 'f9-14-dt13',
        type: NodeType.TABLE,
        name: 'Decision-Table #13',
        position: { x: 3580, y: 640 },
        size: { width: 330, height: 240 },
        ports: ['table-in:left', 'decision-out-row_1:right', 'decision-default:right', 'decision-error:right'],
        groups: [{ group_name: 'row_1', order: 1, valid: true }],
    },
    {
        id: 'f9-12-cdt14',
        type: NodeType.CLASSIFICATION_TABLE,
        name: 'Classification Decision Table #14',
        position: { x: 1480, y: 454 },
        size: { width: 340, height: 780 },
        ports: [
            'table-in:left',
            'decision-route-route_10:right',
            'decision-route-route_08:right',
            'decision-route-route_09:right',
            'decision-route-route_06:right',
            'decision-route-route_07:right',
            'decision-route-route_03:right',
            'decision-route-route_04:right',
            'decision-route-route_01:right',
            'decision-route-route_11:right',
            'decision-route-route_02:right',
            'decision-route-route_05:right',
            'decision-default:right',
            'decision-error:right',
        ],
        groups: [
            { group_name: 'route_10', order: 0, dock_visible: true, route_code: 'route_10' },
            { group_name: 'route_08', order: 1, dock_visible: true, route_code: 'route_08' },
            { group_name: 'route_09', order: 2, dock_visible: true, route_code: 'route_09' },
            { group_name: 'route_06', order: 3, dock_visible: true, route_code: 'route_06' },
            { group_name: 'route_07', order: 4, dock_visible: true, route_code: 'route_07' },
            { group_name: 'route_03', order: 5, dock_visible: true, route_code: 'route_03' },
            { group_name: 'route_04', order: 6, dock_visible: true, route_code: null },
            { group_name: 'route_01', order: 7, dock_visible: true, route_code: 'route_01' },
            { group_name: 'route_11', order: 8, dock_visible: true, route_code: 'route_11' },
            { group_name: 'route_02', order: 9, dock_visible: true, route_code: 'route_02' },
            { group_name: 'route_05', order: 10, dock_visible: true, route_code: 'route_05' },
        ],
    },
];

const FLOW9_CONNECTIONS: [string, string, string, string][] = [
    ['f9-05-py8', 'python-out', 'f9-06-py3', 'python-in'],
    ['f9-01-py4', 'python-out', 'f9-06-py3', 'python-in'],
    ['f9-19-py7', 'python-out', 'f9-06-py3', 'python-in'],
    ['f9-15-agent16', 'agent-out', 'f9-06-py3', 'python-in'],
    ['f9-10-agent15', 'agent-out', 'f9-06-py3', 'python-in'],
    ['f9-16-py2', 'python-out', 'f9-13-py5', 'python-in'],
    ['f9-13-py5', 'python-out', 'f9-20-end', 'end-in'],
    ['f9-08-py6', 'python-out', 'f9-12-cdt14', 'table-in'],
    ['f9-03-py9', 'python-out', 'f9-06-py3', 'python-in'],
    ['f9-11-task17', 'task-out', 'f9-09-py10', 'python-in'],
    ['f9-09-py10', 'python-out', 'f9-16-py2', 'python-in'],
    ['f9-07-py1', 'python-out', 'f9-13-py5', 'python-in'],
    ['f9-06-py3', 'python-out', 'f9-14-dt13', 'table-in'],
    ['f9-04-start', 'start-start', 'f9-18-py11', 'python-in'],
    ['f9-18-py11', 'python-out', 'f9-08-py6', 'python-in'],
    ['f9-17-task18', 'task-out', 'f9-02-dt12', 'table-in'],
    ['f9-02-dt12', 'decision-out-row-2', 'f9-11-task17', 'task-in'],
    ['f9-02-dt12', 'decision-out-row-1', 'f9-13-py5', 'python-in'],
    ['f9-14-dt13', 'decision-out-row_1', 'f9-17-task18', 'task-in'],
    ['f9-14-dt13', 'decision-default', 'f9-02-dt12', 'table-in'],
    ['f9-14-dt13', 'decision-error', 'f9-02-dt12', 'table-in'],
    ['f9-12-cdt14', 'decision-default', 'f9-10-agent15', 'agent-in'],
    ['f9-12-cdt14', 'decision-error', 'f9-05-py8', 'python-in'],
    ['f9-12-cdt14', 'decision-route-route_10', 'f9-07-py1', 'python-in'],
    ['f9-12-cdt14', 'decision-route-route_08', 'f9-05-py8', 'python-in'],
    ['f9-12-cdt14', 'decision-route-route_09', 'f9-03-py9', 'python-in'],
    ['f9-12-cdt14', 'decision-route-route_06', 'f9-01-py4', 'python-in'],
    ['f9-12-cdt14', 'decision-route-route_07', 'f9-01-py4', 'python-in'],
    ['f9-12-cdt14', 'decision-route-route_03', 'f9-19-py7', 'python-in'],
    ['f9-12-cdt14', 'decision-route-route_01', 'f9-05-py8', 'python-in'],
    ['f9-12-cdt14', 'decision-route-route_11', 'f9-01-py4', 'python-in'],
    ['f9-12-cdt14', 'decision-route-route_02', 'f9-19-py7', 'python-in'],
    ['f9-12-cdt14', 'decision-route-route_05', 'f9-15-agent16', 'agent-in'],
];

export function flow9(): FlowFixture {
    return fromDump(FLOW9_NODES, FLOW9_CONNECTIONS);
}

/** The layout pipeline up to the dummy chains, for the fixture's first (largest) component. */
export function layeredComponent({ nodes, connections }: FlowFixture): LayeredGraph {
    const { graph, components } = buildLayoutGraph(nodes, connections);
    const backEdges = findBackEdges(graph, components[0]);
    return splitLongEdges(graph, components[0], assignLayers(graph, components[0], backEdges), backEdges);
}
