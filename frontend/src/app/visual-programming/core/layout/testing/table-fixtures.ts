import { NodeType } from '@shared/models';

import { connect, fixture, FlowFixture, makeNode, tableNode, tableRowRole } from './builders';

/**
 * Synthetic flow with two classification tables: verifies that port-aligned table inputs
 * and multi-row outputs are positioned correctly during layout.
 *
 * Shape: two starts (s1, s2) feeding agent `p` and tall agent `w`; s2 also feeds table `T` (2 rows),
 * whose rows connect to py1 and py2; `p` feeds a 5-row table `cdt`.
 */
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

/**
 * Synthetic flow testing row-pinned child placement: a 2-row CDT with children py1/py2
 * pinned to their respective rows, alongside a tall agent `big` and a small agent `small`.
 *
 * Shape: two starts → agent `p` → 2-row `cdt`; s2 → `u` → `v` → big/small.
 */
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

/**
 * Synthetic flow testing that pinned children are relocated when a table with many rows
 * forces downstream nodes to spread. Two tables feed into further tables and python nodes.
 *
 * Shape: start → 4-row `cdt8` → pn12/pn5/pn11/5-row `cdt10`; start → 3-row `tableY` → python13.
 */
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
