import { IPoint } from '@foblex/2d';
import { NodeType } from '@shared/models';

import { ConnectionModel } from '../../models/connection.model';
import { NodeModel } from '../../models/node.model';
import { connect, FlowFixture, makeNode, port, tableNode, tableRowRole } from './fixtures';

/**
 * Generates a seeded random flow for the quality corpus. The same seed always produces the same
 * graph (deterministic LCG PRNG). Every node gets real ports (plain nodes: `input`/`out0`/`out1`;
 * tables: `table-in` + per-row outputs) and tables get their visual height. Some connections
 * intentionally point at ports that don't exist (`bogus-role`, a table's `input`) to test
 * resilience to stale port references.
 *
 * @param seed - Integer seed for the LCG random number generator. Same seed = same graph.
 * @param options.withTables - When true, ~30% of generated nodes are decision/classification
 *   tables with 0-5 rows. When false, only plain nodes (agent, python, end) are created.
 */
export function randomGraph(seed: number, options: { withTables: boolean }): FlowFixture {
    let state = seed;
    const random = (): number => {
        state = (Math.imul(state, 1103515245) + 12345) & 0x7fffffff;
        return state / 0x80000000;
    };
    const pick = <T>(items: readonly T[]): T => items[Math.floor(random() * items.length)];
    const isTable = (node: NodeModel): boolean =>
        node.type === NodeType.TABLE || node.type === NodeType.CLASSIFICATION_TABLE;
    const rowCounts = new Map<string, number>();

    const plainNode = (id: string, type: NodeType, width: number, height: number): NodeModel =>
        makeNode(id, type, {
            width,
            height,
            ports: [port(id, 'input', 'left'), port(id, 'out0', 'right'), port(id, 'out1', 'right')],
        });

    const nodeCount = 4 + Math.floor(random() * 12);
    const nodes: NodeModel[] = [plainNode('n0', NodeType.START, 125, 60)];
    if (random() < 0.2) nodes.push(plainNode('n1', NodeType.START, 125, 60));
    while (nodes.length < nodeCount) {
        const id = 'n' + nodes.length;
        if (options.withTables && random() < 0.3) {
            const type = pick([NodeType.TABLE, NodeType.CLASSIFICATION_TABLE] as const);
            const rowCount = Math.floor(random() * 6);
            rowCounts.set(id, rowCount);
            nodes.push(tableNode(id, type, rowCount));
        } else {
            const type = pick([NodeType.AGENT, NodeType.PYTHON, NodeType.END]);
            const height = pick([60, 60, 60, 100, 200, 360, 700, 75]);
            const width = pick([330, 330, 200, 450]);
            nodes.push(plainNode(id, type, width, height));
        }
    }

    const sourceRole = (source: NodeModel): string => {
        if (!isTable(source)) return 'out' + Math.floor(random() * 2);
        const rowCount = rowCounts.get(source.id) ?? 0;
        if (rowCount === 0 || random() < 0.1) return 'bogus-role';
        return tableRowRole(
            source.type as NodeType.TABLE | NodeType.CLASSIFICATION_TABLE,
            Math.floor(random() * rowCount)
        );
    };

    const connections: ConnectionModel[] = [];
    let nextConnection = 0;
    const nextId = (): string => 'c' + nextConnection++;
    for (let index = 1; index < nodes.length; index++) {
        const target = nodes[index];
        if (target.type === NodeType.START) continue;
        const parentCount = random() < 0.3 ? 2 : 1;
        for (let parent = 0; parent < parentCount; parent++) {
            const source = nodes[Math.floor(random() * index)];
            const id = nextId();
            connections.push(
                connect(id, source.id, sourceRole(source), target.id, isTable(target) ? 'table-in' : 'input')
            );
            if (isTable(source) && random() < 0.2) {
                const extraId = nextId();
                connections.push(connect(extraId, source.id, sourceRole(source), target.id, 'input'));
            }
        }
    }
    if (random() < 0.3) {
        const from = pick(nodes.slice(1));
        const to = pick(nodes.slice(1));
        connections.push(connect(nextId(), from.id, sourceRole(from), to.id));
    }
    if (random() < 0.05) nodes.push(plainNode('iso', NodeType.AGENT, 330, 60));

    return { nodes, connections };
}

// Column pitch of the scattered layout: wider than the widest generated node (450) plus both
// paddings, both stubs and the x jitter, so no stub ends inside a neighbour column's box.
const SCATTER_COLUMN_PITCH = 600;
const SCATTER_X_JITTERS = [0, 20, 40];
const SCATTER_VERTICAL_GAPS = [20, 40, 60, 80, 120, 200];

/**
 * Produces a hand-made-looking layout for `nodes` by distributing them into random columns on a
 * 600-px pitch with a small x jitter, stacking each column top-to-bottom in random order with
 * random vertical gaps (20-200 px). Everything stays on the 20-px grid and nothing overlaps,
 * but wires may run backwards and between stacked nodes — scenarios an auto-arranged layout
 * never produces (stacked-gap cases). Same seed always gives the same positions.
 *
 * @param nodes - The nodes to scatter. Each node's `size.height` determines vertical spacing.
 * @param seed - Integer seed for the LCG random number generator.
 * @returns A map from node id to the assigned position.
 */
export function scatteredPositions(nodes: NodeModel[], seed: number): Map<string, IPoint> {
    let state = seed;
    const random = (): number => {
        state = (Math.imul(state, 1103515245) + 12345) & 0x7fffffff;
        return state / 0x80000000;
    };
    const pick = <T>(items: readonly T[]): T => items[Math.floor(random() * items.length)];
    const columnCount = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
    const columns: NodeModel[][] = Array.from({ length: columnCount }, () => []);
    for (const node of nodes) columns[Math.floor(random() * columnCount)].push(node);

    const positions = new Map<string, IPoint>();
    columns.forEach((column, columnIndex) => {
        const x = columnIndex * SCATTER_COLUMN_PITCH + pick(SCATTER_X_JITTERS);
        let top = pick([0, 20, 40, 60, 80, 100]);
        const order = column.map((node) => ({ node, key: random() })).sort((first, second) => first.key - second.key);
        for (const { node } of order) {
            positions.set(node.id, { x, y: top });
            // A fixture table's size.height is its visual height (tableNode), so size.height is the box.
            top += node.size.height + pick(SCATTER_VERTICAL_GAPS);
        }
    });
    return positions;
}

/**
 * Deterministic Fisher-Yates shuffle using the same LCG as `randomGraph`, for shuffle-invariance
 * checks (verifying that layout results are independent of input order).
 *
 * @param items - The array to shuffle. Not mutated; returns a new array.
 * @param seed - Integer seed for the LCG random number generator.
 */
export function shuffled<T>(items: T[], seed: number): T[] {
    const copy = [...items];
    let state = seed;
    for (let index = copy.length - 1; index > 0; index--) {
        state = (Math.imul(state, 1103515245) + 12345) & 0x7fffffff;
        const other = state % (index + 1);
        [copy[index], copy[other]] = [copy[other], copy[index]];
    }
    return copy;
}
