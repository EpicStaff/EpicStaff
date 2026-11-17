import { GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { mapGraphDtoToFlowModel } from '../load/map-graph-dto-to-flow-model';
import { LIVE_NODE_ID as ID, liveAgent, liveGraph } from '../testing/live-graph.fixture';
import { buildUuidToBackendIdMap, getConnectionDiff, getNodeDiff } from './diff';
import { buildBulkSavePayload } from './payload';

const STORED_BENDS = [
    { x: 600, y: 30 },
    { x: 600, y: 430 },
];
/** What the router gives a wire it draws itself. */
const ROUTED = [
    { x: 700, y: 30 },
    { x: 700, y: 430 },
];

/**
 * The flow as loaded from the backend:
 * - wire 50 (agent → task) has stored bends, dropped on load because the agent row still holds an
 *   outdated size;
 * - wire 51 (python → task) never had stored bends;
 * - wire 52 (task → end) has stored bends that are restored as hand-placed;
 * - wire 53 (python → end) has its stored bends cleared by an earlier save.
 */
function loadedFlow(): FlowModel {
    const graph: GraphDto = {
        ...liveGraph,
        agent_node_list: [{ ...liveAgent, metadata: { position: { x: 0, y: 0 }, size: { width: 900, height: 40 } } }],
        edge_list: [
            { id: 50, graph: 1, start_node_id: ID.agent, end_node_id: ID.task, metadata: { waypoints: STORED_BENDS } },
            { id: 51, graph: 1, start_node_id: ID.python, end_node_id: ID.task, metadata: {} },
            { id: 52, graph: 1, start_node_id: ID.task, end_node_id: ID.end, metadata: { waypoints: STORED_BENDS } },
            { id: 53, graph: 1, start_node_id: ID.python, end_node_id: ID.end, metadata: { waypoints: [] } },
        ],
    };
    return mapGraphDtoToFlowModel(graph);
}

/** The live flow after the canvas routed every wire it draws itself. */
function routed(flow: FlowModel): FlowModel {
    return {
        ...flow,
        connections: flow.connections.map((connection) =>
            connection.userAdjustedWaypoints ? connection : { ...connection, waypoints: ROUTED }
        ),
    };
}

/** The edge rows the save sends, keyed by edge id (a new edge has none). */
function sentEdges(previous: FlowModel, current: FlowModel): Map<number | undefined, { metadata?: unknown }> {
    const idMap = buildUuidToBackendIdMap(current.nodes);
    const payload = buildBulkSavePayload(
        1,
        getNodeDiff(previous, current),
        getConnectionDiff(previous, current, idMap),
        current,
        idMap,
        1
    );
    const edges = payload['edge_list'] as { id?: number; metadata?: unknown }[];
    return new Map(edges.map((edge) => [edge.id, edge]));
}

describe('saving the bends of plain edges', () => {
    it('clears the stored bends of an edge that was loaded without them', () => {
        const previous = loadedFlow();

        expect(sentEdges(previous, routed(previous)).get(50)?.metadata).toEqual({ waypoints: [] });
    });

    it('sends nothing for an edge that never had stored bends', () => {
        const previous = loadedFlow();

        expect(sentEdges(previous, routed(previous)).has(51)).toBe(false);
    });

    it('sends nothing for an edge whose stored bends an earlier save already cleared', () => {
        const previous = loadedFlow();

        expect(sentEdges(previous, routed(previous)).has(53)).toBe(false);
    });

    it('sends nothing for an edge whose hand-placed bends are unchanged', () => {
        const previous = loadedFlow();

        expect(sentEdges(previous, routed(previous)).has(52)).toBe(false);
    });

    it('sends the new bends of an edge whose hand-placed bends were moved', () => {
        const previous = loadedFlow();
        const moved = [
            { x: 650, y: 30 },
            { x: 650, y: 430 },
        ];
        const current = routed({
            ...previous,
            connections: previous.connections.map((connection) =>
                connection.data?.id === 52 ? { ...connection, waypoints: moved } : connection
            ),
        });

        expect(sentEdges(previous, current).get(52)?.metadata).toEqual({ waypoints: moved });
    });

    it('clears the stored bends of an edge reset to automatic routing, not saving the routed ones', () => {
        const previous = loadedFlow();
        const current = routed({
            ...previous,
            connections: previous.connections.map((connection) =>
                connection.data?.id === 52 ? { ...connection, waypoints: [], userAdjustedWaypoints: false } : connection
            ),
        });

        expect(sentEdges(previous, current).get(52)?.metadata).toEqual({ waypoints: [] });
    });
});
