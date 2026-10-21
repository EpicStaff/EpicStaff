import { NodeType } from '@shared/models';

import { connect, fixture, FlowFixture, makeNode } from './builders';

/**
 * Two nodes in the same column (stacked): Py#14 on top, Py#15 below.
 * The wire from py14 → py15 must route left through the gap between them.
 * The default `targetTop` (120) leaves a 60-px gap between boxes.
 */
export function stackedPair(targetTop = 120): FlowFixture {
    const nodes = [
        makeNode('py14', NodeType.PYTHON, { height: 60, position: { x: 0, y: 0 } }),
        makeNode('py15', NodeType.PYTHON, { height: 60, position: { x: 0, y: targetTop } }),
    ];
    return fixture(nodes, [connect('c14-15', 'py14', 'python-out', 'py15', 'python-in')]);
}

/** A node with a self-loop edge (loop → loop), preceded by a start node. */
export function selfLoop(): FlowFixture {
    const nodes = [
        makeNode('start', NodeType.START, { width: 125, height: 60, position: { x: 0, y: 0 } }),
        makeNode('loop', NodeType.PYTHON, { height: 60, position: { x: 320, y: 0 } }),
    ];
    const connections = [connect('c1', 'start', 'out', 'loop'), connect('c2', 'loop', 'out', 'loop')];
    return fixture(nodes, connections);
}

/** A three-node cycle: start → a → b → c → a. */
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

/** Two disconnected subgraphs: start → a → b, and hook → c → d. */
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

/** Two connected nodes (start → a) plus two isolated nodes with no edges. */
export function isolatedNodes(): FlowFixture {
    const nodes = [
        makeNode('start', NodeType.START, { width: 125, height: 60, position: { x: 0, y: 0 } }),
        makeNode('a', NodeType.AGENT, { height: 60, position: { x: 320, y: 0 } }),
        makeNode('lonely1', NodeType.AGENT, { height: 60, position: { x: 0, y: 300 } }),
        makeNode('lonely2', NodeType.PYTHON, { height: 60, position: { x: 520, y: 300 } }),
    ];
    return fixture(nodes, [connect('c1', 'start', 'out', 'a')]);
}
