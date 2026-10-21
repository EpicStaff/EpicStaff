import { IPoint } from '@foblex/2d';
import { NodeType } from '@shared/models';

import { CustomPortId, ViewPort } from '../../models/port.model';
import { connect, FlowFixture, makeNode, port } from './builders';

/**
 * Captured flows: real flows dumped from the editor, trimmed to geometry only (python code,
 * prompts and backend records dropped). The captured ids are replaced with descriptive ones.
 * Each flow tests layout and routing on realistic, complex graphs.
 */

/** A node captured from the editor (flowService state), trimmed to the geometry. */
interface DumpedNode {
    id: string;
    type: NodeType;
    name: string;
    position: IPoint;
    size: { width: number; height: number };
    /** Port specs: `role:position`, or `role:position:idSuffix` when the port id is not `<nodeId>_<role>`. */
    ports: string[];
    groups?: {
        group_name: string;
        order: number;
        dock_visible?: boolean;
        route_code?: string | null;
        valid?: boolean;
    }[];
}

/**
 * Builds a captured flow's nodes and connections.
 * Connection id format: `sourcePortId+targetPortId`, matching the editor convention.
 */
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

// ---------------------------------------------------------------------------
// flow8: a DAG with two classification tables in series
// ---------------------------------------------------------------------------

/**
 * `flow8` — a captured DAG: Start → Py#10 → CDT#2 (3 rows → Py#3/Audio#4/File#5),
 * CDT#2's error → End. Py#3 → CDT#6 (1 row → Py#9), CDT#6's default/error → End.
 * Audio#4 → Py#7, File#5 → Py#8.
 */
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

// ---------------------------------------------------------------------------
// liveFlow6: a captured flow with three cycles
// ---------------------------------------------------------------------------

/**
 * `liveFlow6` — a captured flow with three back-edges (cycles):
 * Start → Py7 → CDT11, whose rows feed Py1/Py2/Py3 and whose Default and Error both
 * feed End; Py1 → File Extractor 8, Py2 → Audio 9, Py3 → DT10 (rows → Py4, Py5,
 * Default → Py6). Cycles: Py4 → DT10, Py6 → DT10, and Py5 → Py7.
 */
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

// ---------------------------------------------------------------------------
// flow9: a large captured DAG with 11-row CDT and chained decision tables
// ---------------------------------------------------------------------------

/**
 * `flow9` — a large captured DAG. CDT#14 (11 rows, one with null route_code) fans out to 7
 * children, several reachable from multiple rows (Py#8 from route_08, route_01 and Error;
 * Py#4 from route_06, route_07 and route_11; Py#7 from route_03 and route_02).
 * Six children merge into Py#3 → DT#13 → DT#12 → Task#17 → Py#10 → Py#2 → Py#5 → End,
 * and Py#1 skips directly to Py#5.
 */
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
