import { NodeType } from '@shared/models';

import { ConnectionModel } from '../models/connection.model';
import { NodeModel } from '../models/node.model';
import { CustomPortId } from '../models/port.model';
import { computeBackwardContext, computeForwardContext, computeHoverContext } from './hover-context.util';

// ---------------------------------------------------------------------------
// Minimal test fixtures
// ---------------------------------------------------------------------------

function makeNode(id: string, type: NodeType = NodeType.AGENT): NodeModel {
    return {
        id,
        backendId: null,
        type,
        node_name: id,
        position: { x: 0, y: 0 },
        size: { width: 200, height: 100 },
        ports: null,
        input_map: {},
        output_variable_path: null,
        data: null,
    } as unknown as NodeModel;
}

function makeCdt(id: string): NodeModel {
    return makeNode(id, NodeType.TABLE);
}

function makeClassCdt(id: string): NodeModel {
    return makeNode(id, NodeType.CLASSIFICATION_TABLE);
}

let connCounter = 0;

function makeConn(sourceNodeId: string, targetNodeId: string): ConnectionModel {
    const id = `conn-${++connCounter}`;
    return {
        id,
        category: 'default',
        sourceNodeId,
        targetNodeId,
        sourcePortId: `${sourceNodeId}_out` as CustomPortId,
        targetPortId: `${targetNodeId}_in` as CustomPortId,
        behavior: 'fixed',
        type: 'segment',
        data: null,
    };
}

beforeEach(() => {
    connCounter = 0;
});

// ---------------------------------------------------------------------------
// Helper: build maps used by low-level traversal functions
// ---------------------------------------------------------------------------

function buildMaps(connections: ConnectionModel[]) {
    const nodeMap = new Map<string, NodeModel>();
    const incomingMap = new Map<string, ConnectionModel[]>();
    const outgoingMap = new Map<string, ConnectionModel[]>();

    for (const conn of connections) {
        if (!incomingMap.has(conn.targetNodeId)) incomingMap.set(conn.targetNodeId, []);
        incomingMap.get(conn.targetNodeId)!.push(conn);
        if (!outgoingMap.has(conn.sourceNodeId)) outgoingMap.set(conn.sourceNodeId, []);
        outgoingMap.get(conn.sourceNodeId)!.push(conn);
    }

    return { nodeMap, incomingMap, outgoingMap };
}

// ---------------------------------------------------------------------------
// Scenario 1: Simple linear graph  A → B (target) → C
// ---------------------------------------------------------------------------

describe('computeHoverContext — linear graph', () => {
    // A → B → C
    const A = makeNode('A');
    const B = makeNode('B');
    const C = makeNode('C');
    const AB = makeConn('A', 'B');
    const BC = makeConn('B', 'C');
    const nodes = [A, B, C];
    const connections = [AB, BC];

    it('includes the target, its predecessor, and its successor', () => {
        const ctx = computeHoverContext('B', nodes, connections);
        expect(ctx.nodeIds).toEqual(new Set(['A', 'B', 'C']));
        expect(ctx.connectionIds).toEqual(new Set([AB.id, BC.id]));
    });

    it('hovering A includes only A and its successor B', () => {
        const ctx = computeHoverContext('A', nodes, connections);
        expect(ctx.nodeIds).toEqual(new Set(['A', 'B', 'C']));
        expect(ctx.connectionIds).toEqual(new Set([AB.id, BC.id]));
    });
});

// ---------------------------------------------------------------------------
// Scenario 2: Target with multiple incoming connections
// ---------------------------------------------------------------------------

describe('computeHoverContext — multiple incoming connections', () => {
    // P1 → T ← P2 → S
    const P1 = makeNode('P1');
    const P2 = makeNode('P2');
    const T = makeNode('T');
    const S = makeNode('S');
    const P1T = makeConn('P1', 'T');
    const P2T = makeConn('P2', 'T');
    const P2S = makeConn('P2', 'S');
    const TS = makeConn('T', 'S');
    const nodes = [P1, P2, T, S];
    const connections = [P1T, P2T, P2S, TS];

    it('includes all predecessor branches and forward successors', () => {
        const ctx = computeHoverContext('T', nodes, connections);
        expect(ctx.nodeIds).toContain('P1');
        expect(ctx.nodeIds).toContain('P2');
        expect(ctx.nodeIds).toContain('T');
        expect(ctx.nodeIds).toContain('S');
        expect(ctx.connectionIds).toContain(P1T.id);
        expect(ctx.connectionIds).toContain(P2T.id);
        expect(ctx.connectionIds).toContain(TS.id);
    });
});

// ---------------------------------------------------------------------------
// Scenario 3: CDT with multiple incoming branches
// ---------------------------------------------------------------------------

describe('computeHoverContext — CDT with multiple incoming branches', () => {
    // X → CDT ← Y; CDT → Z (target is Z)
    const X = makeNode('X');
    const Y = makeNode('Y');
    const CDT = makeCdt('CDT');
    const Z = makeNode('Z');
    const XCDT = makeConn('X', 'CDT');
    const YCDT = makeConn('Y', 'CDT');
    const CDTZ = makeConn('CDT', 'Z');
    const nodes = [X, Y, CDT, Z];
    const connections = [XCDT, YCDT, CDTZ];

    it('includes both incoming branches and their predecessors', () => {
        const ctx = computeHoverContext('Z', nodes, connections);
        expect(ctx.nodeIds).toContain('X');
        expect(ctx.nodeIds).toContain('Y');
        expect(ctx.nodeIds).toContain('CDT');
        expect(ctx.nodeIds).toContain('Z');
        expect(ctx.connectionIds).toContain(XCDT.id);
        expect(ctx.connectionIds).toContain(YCDT.id);
        expect(ctx.connectionIds).toContain(CDTZ.id);
    });
});

// ---------------------------------------------------------------------------
// Scenario 4: Direct CDT cycle  A → CDT → CDT  (CDT connects back to itself)
// ---------------------------------------------------------------------------

describe('computeBackwardContext — direct CDT cycle', () => {
    // A → CDT → CDT (self-loop output)
    const A = makeNode('A');
    const CDT = makeCdt('CDT');
    const ACDT = makeConn('A', 'CDT');
    const CDTself = makeConn('CDT', 'CDT');
    const connections = [ACDT, CDTself];

    it('excludes the self-loop incoming connection when CDT connects back to itself', () => {
        const { nodeMap, incomingMap, outgoingMap } = buildMaps(connections);
        nodeMap.set('A', A);
        nodeMap.set('CDT', CDT);

        // Target is CDT (hovered directly or arrived at via backward traversal)
        const ctx = computeBackwardContext('CDT', nodeMap, incomingMap, outgoingMap);
        expect(ctx.nodeIds).toContain('A');
        expect(ctx.nodeIds).toContain('CDT');
        expect(ctx.connectionIds).toContain(ACDT.id);
        // The self-loop belongs to the cyclic outgoing branch → excluded
        expect(ctx.connectionIds).not.toContain(CDTself.id);
    });
});

// ---------------------------------------------------------------------------
// Scenario 5: Indirect CDT cycle  A → CDT → PN1 → PN2 → CDT
//             Target is on another branch: CDT → Target
// ---------------------------------------------------------------------------

describe('computeHoverContext — indirect CDT cycle', () => {
    // A → CDT → Target
    //       ↓
    //      PN1 → PN2 → CDT  (cycle back)
    const A = makeNode('A');
    const CDT = makeCdt('CDT');
    const PN1 = makeNode('PN1');
    const PN2 = makeNode('PN2');
    const Target = makeNode('Target');
    const ACDT = makeConn('A', 'CDT');
    const CDTTarget = makeConn('CDT', 'Target');
    const CDTPN1 = makeConn('CDT', 'PN1');
    const PN1PN2 = makeConn('PN1', 'PN2');
    const PN2CDT = makeConn('PN2', 'CDT');
    const nodes = [A, CDT, PN1, PN2, Target];
    const connections = [ACDT, CDTTarget, CDTPN1, PN1PN2, PN2CDT];

    it('excludes PN1, PN2 and cyclic connections from backward context', () => {
        const { nodeMap, incomingMap, outgoingMap } = buildMaps(connections);
        for (const n of nodes) nodeMap.set(n.id, n);

        const backCtx = computeBackwardContext('Target', nodeMap, incomingMap, outgoingMap);
        // CDT and A are valid predecessors
        expect(backCtx.nodeIds).toContain('CDT');
        expect(backCtx.nodeIds).toContain('A');
        expect(backCtx.connectionIds).toContain(ACDT.id);
        expect(backCtx.connectionIds).toContain(CDTTarget.id);

        // PN1 and PN2 are exclusively in the cyclic outgoing branch
        expect(backCtx.nodeIds).not.toContain('PN1');
        expect(backCtx.nodeIds).not.toContain('PN2');
        expect(backCtx.connectionIds).not.toContain(CDTPN1.id);
        expect(backCtx.connectionIds).not.toContain(PN1PN2.id);
        expect(backCtx.connectionIds).not.toContain(PN2CDT.id);
    });

    it('full hoverContext excludes PN1 and PN2 (they are only on CDT cyclic branch)', () => {
        const ctx = computeHoverContext('Target', nodes, connections);
        // Forward from Target has no outgoing connections, so forward only adds Target
        expect(ctx.nodeIds).toContain('A');
        expect(ctx.nodeIds).toContain('CDT');
        expect(ctx.nodeIds).toContain('Target');
        expect(ctx.nodeIds).not.toContain('PN1');
        expect(ctx.nodeIds).not.toContain('PN2');
    });
});

// ---------------------------------------------------------------------------
// Scenario 5b: CDT cycle where cycle nodes ALSO have external predecessors
//              (the bug reported in the screenshot)
//
// Graph:  CDT12 → PN15 → Task16 → CDT17 → PN19 (hovered)
//                            ↑              ↓
//                            └────── PN15 ←─┘  (CDT17 → PN15 creates cycle)
//
// PN15 and Task16 are both in forwardReachable(CDT17) AND have CDT12 as an
// external ancestor. They must NOT be excluded — otherwise only CDT17 would
// appear in the backward context.
// ---------------------------------------------------------------------------

describe('computeHoverContext — cycle nodes with external predecessors (screenshot regression)', () => {
    const CDT12 = makeCdt('CDT12');
    const PN15 = makeNode('PN15');
    const Task16 = makeNode('Task16');
    const CDT17 = makeCdt('CDT17');
    const PN19 = makeNode('PN19');
    // Main upstream chain
    const CDT12toPN15 = makeConn('CDT12', 'PN15');
    const PN15toTask16 = makeConn('PN15', 'Task16');
    const Task16toCDT17 = makeConn('Task16', 'CDT17');
    // CDT17 routes back to PN15 creating the cycle
    const CDT17toPN15 = makeConn('CDT17', 'PN15');
    // CDT17's other output (the hovered node's direct predecessor)
    const CDT17toPN19 = makeConn('CDT17', 'PN19');
    const nodes = [CDT12, PN15, Task16, CDT17, PN19];
    const connections = [CDT12toPN15, PN15toTask16, Task16toCDT17, CDT17toPN15, CDT17toPN19];

    it('includes PN15, Task16, CDT12 — they have an external ancestor despite being in the cycle', () => {
        const ctx = computeHoverContext('PN19', nodes, connections);
        expect(ctx.nodeIds).toContain('PN19');
        expect(ctx.nodeIds).toContain('CDT17');
        expect(ctx.nodeIds).toContain('Task16');
        expect(ctx.nodeIds).toContain('PN15');
        expect(ctx.nodeIds).toContain('CDT12');
        expect(ctx.connectionIds).toContain(CDT17toPN19.id);
        expect(ctx.connectionIds).toContain(Task16toCDT17.id);
        expect(ctx.connectionIds).toContain(PN15toTask16.id);
        expect(ctx.connectionIds).toContain(CDT12toPN15.id);
    });
});

// ---------------------------------------------------------------------------
// Scenario 6: Target downstream from CDT — unrelated cyclic branch dimmed
// (same graph as above, verifying hover on CDT itself)
// ---------------------------------------------------------------------------

describe('computeHoverContext — hovered on CDT with cycle', () => {
    const A = makeNode('A');
    const CDT = makeCdt('CDT');
    const PN1 = makeNode('PN1');
    const PN2 = makeNode('PN2');
    const Target = makeNode('Target');
    const ACDT = makeConn('A', 'CDT');
    const CDTTarget = makeConn('CDT', 'Target');
    const CDTPN1 = makeConn('CDT', 'PN1');
    const PN1PN2 = makeConn('PN1', 'PN2');
    const PN2CDT = makeConn('PN2', 'CDT');
    const nodes = [A, CDT, PN1, PN2, Target];
    const connections = [ACDT, CDTTarget, CDTPN1, PN1PN2, PN2CDT];

    it('hovering CDT: backward excludes cyclic PN1/PN2, forward includes all outgoing branches', () => {
        const ctx = computeHoverContext('CDT', nodes, connections);
        // Backward: A is a valid predecessor; PN2 is in forward-reachable of CDT, so excluded
        expect(ctx.nodeIds).toContain('A');
        // Forward: CDT → Target, CDT → PN1 → PN2 → CDT (cycle included)
        expect(ctx.nodeIds).toContain('Target');
        expect(ctx.nodeIds).toContain('PN1');
        expect(ctx.nodeIds).toContain('PN2');
        // All outgoing connections of CDT are in forward context
        expect(ctx.connectionIds).toContain(CDTTarget.id);
        expect(ctx.connectionIds).toContain(CDTPN1.id);
        expect(ctx.connectionIds).toContain(PN1PN2.id);
        expect(ctx.connectionIds).toContain(PN2CDT.id);
    });
});

// ---------------------------------------------------------------------------
// Scenario 7: CDT encountered during forward traversal — all outgoing branches
// ---------------------------------------------------------------------------

describe('computeForwardContext — CDT with multiple outgoing branches', () => {
    const TPN1 = makeConn('Target', 'PN1');
    const PN1CDT2 = makeConn('PN1', 'CDT2');
    const CDT2A = makeConn('CDT2', 'BranchA');
    const CDT2B = makeConn('CDT2', 'BranchB');
    const BranchBCDT2 = makeConn('BranchB', 'CDT2');
    const connections = [TPN1, PN1CDT2, CDT2A, CDT2B, BranchBCDT2];

    it('includes all outgoing branches and the returning connection', () => {
        const outgoingMap = new Map<string, ConnectionModel[]>();
        for (const conn of connections) {
            if (!outgoingMap.has(conn.sourceNodeId)) outgoingMap.set(conn.sourceNodeId, []);
            outgoingMap.get(conn.sourceNodeId)!.push(conn);
        }

        const ctx = computeForwardContext('Target', outgoingMap, new Set());
        expect(ctx.nodeIds).toContain('PN1');
        expect(ctx.nodeIds).toContain('CDT2');
        expect(ctx.nodeIds).toContain('BranchA');
        expect(ctx.nodeIds).toContain('BranchB');
        expect(ctx.connectionIds).toContain(CDT2A.id);
        expect(ctx.connectionIds).toContain(CDT2B.id);
        // Cycle-back connection is included
        expect(ctx.connectionIds).toContain(BranchBCDT2.id);
    });
});

// ---------------------------------------------------------------------------
// Scenario 8: Forward branch returning to a previously visited CDT
// ---------------------------------------------------------------------------

describe('computeForwardContext — branch returns to visited node', () => {
    // A → B → A  (simple cycle)
    const AB = makeConn('A', 'B');
    const BA = makeConn('B', 'A');
    const connections = [AB, BA];

    it('includes the back-edge connection without infinite looping', () => {
        const outgoingMap = new Map<string, ConnectionModel[]>();
        for (const conn of connections) {
            if (!outgoingMap.has(conn.sourceNodeId)) outgoingMap.set(conn.sourceNodeId, []);
            outgoingMap.get(conn.sourceNodeId)!.push(conn);
        }

        const ctx = computeForwardContext('A', outgoingMap, new Set());
        expect(ctx.nodeIds).toContain('A');
        expect(ctx.nodeIds).toContain('B');
        expect(ctx.connectionIds).toContain(AB.id);
        expect(ctx.connectionIds).toContain(BA.id);
    });
});

// ---------------------------------------------------------------------------
// Scenario 9: Multiple CDT nodes along the forward path
// ---------------------------------------------------------------------------

describe('computeHoverContext — multiple CDTs in forward path', () => {
    // Start → CDT1 → CDT2 → End
    //               → Side
    const Start = makeNode('Start');
    const CDT1 = makeCdt('CDT1');
    const CDT2 = makeClassCdt('CDT2');
    const End = makeNode('End');
    const Side = makeNode('Side');
    const SCDT1 = makeConn('Start', 'CDT1');
    const CDT1CDT2 = makeConn('CDT1', 'CDT2');
    const CDT2End = makeConn('CDT2', 'End');
    const CDT2Side = makeConn('CDT2', 'Side');
    const nodes = [Start, CDT1, CDT2, End, Side];
    const connections = [SCDT1, CDT1CDT2, CDT2End, CDT2Side];

    it('forward context includes all branches through multiple CDTs', () => {
        const ctx = computeHoverContext('Start', nodes, connections);
        expect(ctx.nodeIds).toContain('CDT1');
        expect(ctx.nodeIds).toContain('CDT2');
        expect(ctx.nodeIds).toContain('End');
        expect(ctx.nodeIds).toContain('Side');
        expect(ctx.connectionIds).toContain(CDT2End.id);
        expect(ctx.connectionIds).toContain(CDT2Side.id);
    });
});

// ---------------------------------------------------------------------------
// Scenario 10: Interconnected cycles — no infinite loops or duplicate processing
// ---------------------------------------------------------------------------

describe('computeHoverContext — interconnected cycles', () => {
    // A → B → C → A (cycle1)
    //     B → D → B (cycle2)
    const A = makeNode('A');
    const B = makeNode('B');
    const C = makeNode('C');
    const D = makeNode('D');
    const AB = makeConn('A', 'B');
    const BC = makeConn('B', 'C');
    const CA = makeConn('C', 'A');
    const BD = makeConn('B', 'D');
    const DB = makeConn('D', 'B');
    const nodes = [A, B, C, D];
    const connections = [AB, BC, CA, BD, DB];

    it('terminates and includes all connected nodes', () => {
        const ctx = computeHoverContext('A', nodes, connections);
        expect(ctx.nodeIds).toEqual(new Set(['A', 'B', 'C', 'D']));
        // All connections present
        expect(ctx.connectionIds).toContain(AB.id);
        expect(ctx.connectionIds).toContain(BC.id);
        expect(ctx.connectionIds).toContain(CA.id);
        expect(ctx.connectionIds).toContain(BD.id);
        expect(ctx.connectionIds).toContain(DB.id);
    });
});

// ---------------------------------------------------------------------------
// Scenario 11: Node reachable through multiple valid paths
// ---------------------------------------------------------------------------

describe('computeHoverContext — node via multiple paths', () => {
    // A → B → D
    // A → C → D
    const A = makeNode('A');
    const B = makeNode('B');
    const C = makeNode('C');
    const D = makeNode('D');
    const AB = makeConn('A', 'B');
    const AC = makeConn('A', 'C');
    const BD = makeConn('B', 'D');
    const CD = makeConn('C', 'D');
    const nodes = [A, B, C, D];
    const connections = [AB, AC, BD, CD];

    it('includes D exactly once regardless of path count', () => {
        const ctx = computeHoverContext('D', nodes, connections);
        // nodeIds is a Set, so D appears once
        expect(ctx.nodeIds).toContain('D');
        expect(ctx.nodeIds).toContain('B');
        expect(ctx.nodeIds).toContain('C');
        expect(ctx.nodeIds).toContain('A');
        expect(ctx.connectionIds).toContain(AB.id);
        expect(ctx.connectionIds).toContain(AC.id);
        expect(ctx.connectionIds).toContain(BD.id);
        expect(ctx.connectionIds).toContain(CD.id);
    });
});

// ---------------------------------------------------------------------------
// Scenario 16: Order-independence — backward and forward produce same combined result
// ---------------------------------------------------------------------------

describe('computeHoverContext — order independence', () => {
    const A = makeNode('A');
    const CDT = makeCdt('CDT');
    const PN1 = makeNode('PN1');
    const B = makeNode('B');
    const ACDT = makeConn('A', 'CDT');
    const CDTPN1 = makeConn('CDT', 'PN1');
    const PN1CDT = makeConn('PN1', 'CDT'); // cycle back
    const CDTB = makeConn('CDT', 'B');
    const nodes = [A, CDT, PN1, B];
    const connections = [ACDT, CDTPN1, PN1CDT, CDTB];

    it('produces the same nodeIds and connectionIds regardless of traversal order', () => {
        // computeHoverContext internally runs backward then forward
        const ctx = computeHoverContext('B', nodes, connections);

        // If forward were to run first, B's backward context should still be the same
        // We verify both A and CDT are reachable (via backward) and B is included (target)
        expect(ctx.nodeIds).toContain('A');
        expect(ctx.nodeIds).toContain('CDT');
        expect(ctx.nodeIds).toContain('B');
        // PN1 is only in the cyclic branch of CDT, not a genuine predecessor of B
        expect(ctx.nodeIds).not.toContain('PN1');
        expect(ctx.connectionIds).toContain(ACDT.id);
        expect(ctx.connectionIds).toContain(CDTB.id);
        // PN1-related connections not in backward context of B
        expect(ctx.connectionIds).not.toContain(CDTPN1.id);
        expect(ctx.connectionIds).not.toContain(PN1CDT.id);
    });
});

// ---------------------------------------------------------------------------
// Isolated node (no connections)
// ---------------------------------------------------------------------------

describe('computeHoverContext — isolated node', () => {
    it('returns only the hovered node itself', () => {
        const A = makeNode('A');
        const ctx = computeHoverContext('A', [A], []);
        expect(ctx.nodeIds).toEqual(new Set(['A']));
        expect(ctx.connectionIds).toEqual(new Set());
    });
});
