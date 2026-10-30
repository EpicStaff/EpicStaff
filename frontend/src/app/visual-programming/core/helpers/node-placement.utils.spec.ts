import { NodeType } from '@shared/models';

import { NodeModel } from '../models/node.model';
import {
    CollisionBounds,
    findNearestFreePosition,
    getCollisionBounds,
    getExactBounds,
    GRID_CELL_SIZE,
    hasCollision,
    resolveOverlapsForNode,
    snapPointToGrid,
    snapToGrid,
} from './node-placement.utils';

function makeNode(overrides: Partial<NodeModel> & { id: string; position: { x: number; y: number } }): NodeModel {
    return {
        backendId: null,
        type: NodeType.AGENT,
        node_name: 'test',
        ports: null,
        input_map: {},
        output_variable_path: null,
        size: { width: 330, height: 60 },
        data: { name: '', agent: null, skills: [], model: null, llmConfig: null },
        ...overrides,
    } as NodeModel;
}

describe('snapToGrid', () => {
    it.each([
        [0, 0],
        [20, 20],
        [40, 40],
        [-20, -20],
        [-40, -40],
        [10, 20],
        [9, 0],
        [11, 20],
        [30, 40],
        [29, 20],
        [100, 100],
        [-100, -100],
    ])('snaps %d to %d', (input, expected) => {
        expect(snapToGrid(input)).toBe(expected);
    });

    it('snaps the exact negative half-step to zero', () => {
        // Math.round(-0.5) returns -0 in IEEE 754; the grid value is still 0
        expect(snapToGrid(-10)).toEqual(-0);
    });
});

describe('snapPointToGrid', () => {
    it('snaps both x and y to the grid', () => {
        expect(snapPointToGrid({ x: 13, y: 27 })).toEqual({ x: 20, y: 20 });
    });

    it('handles negative coordinates', () => {
        expect(snapPointToGrid({ x: -13, y: -27 })).toEqual({ x: -20, y: -20 });
    });

    it('leaves already-snapped values unchanged', () => {
        expect(snapPointToGrid({ x: 60, y: 80 })).toEqual({ x: 60, y: 80 });
    });
});

describe('getCollisionBounds', () => {
    it('adds 30px padding for a default node type', () => {
        const node = makeNode({ id: 'n1', position: { x: 0, y: 0 }, size: { width: 330, height: 60 } });
        const bounds = getCollisionBounds(node);

        expect(bounds).toEqual({ width: 360, height: 90, offsetX: -15, offsetY: -15 });
    });

    it('returns table-specific bounds for a TABLE node', () => {
        const node = makeNode({
            id: 'n1',
            position: { x: 0, y: 0 },
            type: NodeType.TABLE,
            size: { width: 330, height: 300 },
            data: { name: 'dt', table: { condition_groups: [], default_next_node: null, next_error_node: null } },
        });
        const bounds = getCollisionBounds(node);

        expect(bounds.width).toBe(370);
        expect(bounds.offsetX).toBe(-20);
        expect(bounds.offsetY).toBe(-15);
    });

    it('returns classification-table-specific bounds for a CLASSIFICATION_TABLE node', () => {
        const node = makeNode({
            id: 'n1',
            position: { x: 0, y: 0 },
            type: NodeType.CLASSIFICATION_TABLE,
            size: { width: 330, height: 300 },
            data: {
                name: 'cdt',
                table: {
                    condition_groups: [],
                    pre_computation_code: '',
                    default_next_node: null,
                    next_error_node: null,
                },
            },
        });
        const bounds = getCollisionBounds(node);

        expect(bounds.width).toBe(370);
        expect(bounds.offsetX).toBe(-20);
        expect(bounds.offsetY).toBe(-15);
    });
});

describe('getExactBounds', () => {
    it('returns the node size with zero offsets', () => {
        const node = makeNode({ id: 'n1', position: { x: 0, y: 0 }, size: { width: 200, height: 100 } });
        expect(getExactBounds(node)).toEqual({ width: 200, height: 100, offsetX: 0, offsetY: 0 });
    });
});

describe('hasCollision', () => {
    const bounds: CollisionBounds = { width: 100, height: 50, offsetX: 0, offsetY: 0 };

    it('returns true when nodes overlap', () => {
        const otherNode = makeNode({
            id: 'other',
            position: { x: 50, y: 20 },
            size: { width: 100, height: 50 },
        });
        const result = hasCollision({ x: 0, y: 0 }, bounds, [otherNode], getExactBounds);
        expect(result).toBe(true);
    });

    it('returns false when nodes do not overlap', () => {
        const otherNode = makeNode({
            id: 'other',
            position: { x: 500, y: 500 },
            size: { width: 100, height: 50 },
        });
        const result = hasCollision({ x: 0, y: 0 }, bounds, [otherNode], getExactBounds);
        expect(result).toBe(false);
    });

    it('returns false when there are no other nodes', () => {
        expect(hasCollision({ x: 0, y: 0 }, bounds, [])).toBe(false);
    });

    it('returns false when nodes are exactly adjacent (no overlap)', () => {
        const otherNode = makeNode({
            id: 'other',
            position: { x: 100, y: 0 },
            size: { width: 100, height: 50 },
        });
        const result = hasCollision({ x: 0, y: 0 }, bounds, [otherNode], getExactBounds);
        expect(result).toBe(false);
    });
});

describe('findNearestFreePosition', () => {
    const bounds: CollisionBounds = { width: 100, height: 50, offsetX: 0, offsetY: 0 };

    it('returns the proposed position when there is no collision', () => {
        const proposed = { x: 0, y: 0 };
        const result = findNearestFreePosition(proposed, bounds, [], getExactBounds);
        expect(result).toEqual(proposed);
    });

    it('finds a nearby free position when collision exists', () => {
        const blocker = makeNode({
            id: 'blocker',
            position: { x: 0, y: 0 },
            size: { width: 100, height: 50 },
        });

        const proposed = { x: 10, y: 10 };
        const result = findNearestFreePosition(proposed, bounds, [blocker], getExactBounds);

        // The result should differ from the proposed position
        expect(result.x !== proposed.x || result.y !== proposed.y).toBe(true);
        // The result should be snapped to the grid
        expect(result.x % GRID_CELL_SIZE).toBe(proposed.x % GRID_CELL_SIZE);
        expect(result.y % GRID_CELL_SIZE).toBe(proposed.y % GRID_CELL_SIZE);
    });

    it('returns proposed position as fallback when no free spot in search radius', () => {
        // Create a wall of nodes that fills the entire search radius
        const nodes: NodeModel[] = [];
        for (let dx = -50; dx <= 50; dx++) {
            for (let dy = -50; dy <= 50; dy++) {
                nodes.push(
                    makeNode({
                        id: `n_${dx}_${dy}`,
                        position: { x: dx * GRID_CELL_SIZE, y: dy * GRID_CELL_SIZE },
                        size: { width: GRID_CELL_SIZE, height: GRID_CELL_SIZE },
                    })
                );
            }
        }

        const proposed = { x: 0, y: 0 };
        const result = findNearestFreePosition(proposed, bounds, nodes, getExactBounds);
        // When exhausted, returns the original proposed position
        expect(result).toEqual(proposed);
    });
});

describe('resolveOverlapsForNode', () => {
    it('returns empty array when anchor node is not found', () => {
        const nodes = [makeNode({ id: 'a', position: { x: 0, y: 0 } })];
        expect(resolveOverlapsForNode('nonexistent', nodes)).toEqual([]);
    });

    it('returns empty array when no nodes overlap the anchor', () => {
        const anchor = makeNode({ id: 'anchor', position: { x: 0, y: 0 } });
        const distant = makeNode({ id: 'far', position: { x: 1000, y: 1000 } });
        expect(resolveOverlapsForNode('anchor', [anchor, distant])).toEqual([]);
    });

    it('moves overlapping nodes to free positions', () => {
        const anchor = makeNode({ id: 'anchor', position: { x: 0, y: 0 } });
        const overlapping = makeNode({ id: 'overlap', position: { x: 10, y: 10 } });

        const moved = resolveOverlapsForNode('anchor', [anchor, overlapping]);

        expect(moved.length).toBe(1);
        expect(moved[0].id).toBe('overlap');
        // The moved node should be at a different position than its original
        expect(moved[0].position.x !== 10 || moved[0].position.y !== 10).toBe(true);
    });

    it('does not include the anchor node in the result', () => {
        const anchor = makeNode({ id: 'anchor', position: { x: 0, y: 0 } });
        const overlapping = makeNode({ id: 'overlap', position: { x: 5, y: 5 } });

        const moved = resolveOverlapsForNode('anchor', [anchor, overlapping]);
        expect(moved.every((n) => n.id !== 'anchor')).toBe(true);
    });
});
