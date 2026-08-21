/**
 * Pure layout pass: a built tree → absolute block coordinates.
 *
 * The graph is a caterpillar — a vertical spine of diamonds with fixed-length
 * horizontal chains hanging off each `yes` branch — so a layered engine (dagre,
 * ELK) would buy nothing: there are no crossings to minimise, and both engines
 * permute nodes within a layer, which would break the hard requirement that rows
 * appear in evaluation order. Plain arithmetic is also deterministic, which is
 * what makes "recomputed on every open" read as stable rather than jittery.
 */

import {
    CDT_TREE_ERROR_LANE_GAP,
    CDT_TREE_H_GAP,
    CDT_TREE_V_GAP,
    SHAPE_BY_KIND,
    SIZE_BY_SHAPE,
} from './cdt-decision-tree.constants';
import {
    CdtTree,
    CdtTreeBlock,
    CdtTreeConnector,
    CdtTreeLayout,
    CdtTreePoint,
    CdtTreePositionedBlock,
    CdtTreeSize,
    inputConnectorId,
    outputConnectorId,
} from './cdt-decision-tree.model';

function push(target: Map<string, CdtTreeConnector[]>, blockId: string, connector: CdtTreeConnector): void {
    const existing = target.get(blockId);
    if (existing) {
        existing.push(connector);
    } else {
        target.set(blockId, [connector]);
    }
}

export function layoutCdtDecisionTree(tree: CdtTree): CdtTreeLayout {
    const byId = new Map<string, CdtTreeBlock>(tree.blocks.map((block) => [block.id, block]));
    const positions = new Map<string, CdtTreePoint>();

    // The builder guarantees every id in `spine`, `chains` and `errorBlockId` is
    // also in `blocks`. Fail loudly with the offending id if that ever stops
    // holding, rather than dying on `undefined.kind` three frames away.
    const blockById = (id: string): CdtTreeBlock => {
        const block = byId.get(id);
        if (!block) throw new Error(`cdt-decision-tree: layout references unknown block "${id}"`);
        return block;
    };

    const sizeOf = (id: string): CdtTreeSize => SIZE_BY_SHAPE[SHAPE_BY_KIND[blockById(id).kind]];

    // 1. The spine runs straight down, every block centred on x = 0.
    let cursorY = 0;
    const spineCentreY = new Map<string, number>();

    for (const id of tree.spine) {
        const size = sizeOf(id);
        positions.set(id, { x: -size.width / 2, y: cursorY });
        spineCentreY.set(id, cursorY + size.height / 2);
        cursorY += size.height + CDT_TREE_V_GAP;
    }

    // 2. Each row's chain runs right from its diamond, vertically centred on it.
    for (const chain of tree.chains) {
        const decisionSize = sizeOf(chain.decisionId);
        const decisionRight = decisionSize.width / 2;
        const centreY = spineCentreY.get(chain.decisionId) ?? 0;

        let cursorX = decisionRight + CDT_TREE_H_GAP;
        for (const id of chain.blockIds) {
            const size = sizeOf(id);
            positions.set(id, { x: cursorX, y: centreY - size.height / 2 });
            cursorX += size.width + CDT_TREE_H_GAP;
        }
    }

    // 3. The error lane sits left of the spine, level with the fall-through block.
    const errorSize = sizeOf(tree.errorBlockId);
    const widestSpine = Math.max(...tree.spine.map((id) => sizeOf(id).width));
    const errorAnchorY = spineCentreY.get(tree.fallThroughBlockId) ?? 0;
    positions.set(tree.errorBlockId, {
        x: -widestSpine / 2 - CDT_TREE_ERROR_LANE_GAP - errorSize.width,
        y: errorAnchorY - errorSize.height / 2,
    });

    // 4. One connector per edge endpoint, so no two edges can ever share one.
    const outPorts = new Map<string, CdtTreeConnector[]>();
    const inPorts = new Map<string, CdtTreeConnector[]>();
    for (const edge of tree.edges) {
        push(outPorts, edge.from, { id: outputConnectorId(edge.id), side: edge.fromSide });
        push(inPorts, edge.to, { id: inputConnectorId(edge.id), side: edge.toSide });
    }

    // 5. Normalise to the origin so tests can compare coordinates directly and
    //    `fitToScreen` has a clean bounding box to work with.
    const placed: CdtTreePositionedBlock[] = tree.blocks.map((block) => {
        const shape = SHAPE_BY_KIND[block.kind];
        return {
            ...block,
            shape,
            size: SIZE_BY_SHAPE[shape],
            position: positions.get(block.id) ?? { x: 0, y: 0 },
            outPorts: outPorts.get(block.id) ?? [],
            inPorts: inPorts.get(block.id) ?? [],
        };
    });

    const minX = Math.min(...placed.map((block) => block.position.x));
    const minY = Math.min(...placed.map((block) => block.position.y));
    const maxX = Math.max(...placed.map((block) => block.position.x + block.size.width));
    const maxY = Math.max(...placed.map((block) => block.position.y + block.size.height));

    return {
        title: tree.title,
        blocks: placed.map((block) => ({
            ...block,
            position: { x: block.position.x - minX, y: block.position.y - minY },
        })),
        edges: tree.edges,
        bounds: { width: maxX - minX, height: maxY - minY },
        hiddenRowCount: tree.hiddenRowCount,
        rowCount: tree.rowCount,
    };
}
