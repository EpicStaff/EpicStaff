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
    CDT_TREE_ASIDE_GAP,
    CDT_TREE_BLOCK_TITLE_BAND,
    CDT_TREE_H_GAP,
    CDT_TREE_SUBTITLE_CODE_LINES,
    CDT_TREE_SUBTITLE_LINE_HEIGHT,
    CDT_TREE_V_GAP,
    MIN_SIZE_BY_SHAPE,
    SHAPE_BY_KIND,
} from './cdt-decision-tree.constants';
import {
    CdtTree,
    CdtTreeBlock,
    CdtTreeConnector,
    CdtTreeLayout,
    CdtTreePoint,
    CdtTreePortSide,
    CdtTreePositionedBlock,
    CdtTreeSize,
    inputConnectorId,
    outputConnectorId,
} from './cdt-decision-tree.model';

/**
 * A block's box: the shape's width, and its minimum height unless a subtitle
 * needs more.
 *
 * The subtitle clamps to a fixed number of lines in CSS, so the room it needs is
 * known without measuring anything — reserve exactly that, whether or not the
 * text fills it. A decision diamond's minimum already exceeds any content, so it
 * is always the minimum.
 */
function blockSize(block: CdtTreeBlock): CdtTreeSize {
    const { width, height: min } = MIN_SIZE_BY_SHAPE[SHAPE_BY_KIND[block.kind]];
    const subtitleBand = block.subtitle ? CDT_TREE_SUBTITLE_CODE_LINES * CDT_TREE_SUBTITLE_LINE_HEIGHT : 0;

    return { width, height: Math.max(min, CDT_TREE_BLOCK_TITLE_BAND + subtitleBand) };
}

/** One end of one edge, before it knows where along its side it sits. */
interface Endpoint {
    readonly blockId: string;
    readonly side: CdtTreePortSide;
    readonly id: string;
    readonly out: boolean;
}

function collect(target: Map<string, Endpoint[]>, endpoint: Endpoint): void {
    const key = `${endpoint.blockId}|${endpoint.side}`;
    const existing = target.get(key);
    if (existing) {
        existing.push(endpoint);
    } else {
        target.set(key, [endpoint]);
    }
}

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

    // The builder guarantees every id named by a lane is also in `blocks`. Fail
    // loudly with the offending id if that ever stops holding, rather than dying
    // on `undefined.kind` three frames away.
    const blockById = (id: string): CdtTreeBlock => {
        const block = byId.get(id);
        if (!block) throw new Error(`cdt-decision-tree: layout references unknown block "${id}"`);
        return block;
    };

    const sizeOf = (id: string): CdtTreeSize => blockSize(blockById(id));

    // The passes run in dependency order rather than in lane order: a chain is
    // centred on its anchor and an aside clears the whole spine, so the spine has
    // to be placed first. Anything that needs a different order needs a new pass,
    // not a reordered `lanes`.
    const spineLane = tree.lanes.find((lane) => lane.kind === 'spine');
    if (!spineLane) throw new Error('cdt-decision-tree: layout found no spine lane');

    // 1. The spine runs straight down, every block centred on x = 0.
    let cursorY = 0;
    const spineCentreY = new Map<string, number>();

    for (const id of spineLane.blockIds) {
        const size = sizeOf(id);
        positions.set(id, { x: -size.width / 2, y: cursorY });
        spineCentreY.set(id, cursorY + size.height / 2);
        cursorY += size.height + CDT_TREE_V_GAP;
    }

    const spineHalfWidth = Math.max(...spineLane.blockIds.map((id) => sizeOf(id).width)) / 2;

    // 2. Each chain runs right from its anchor, vertically centred on it.
    for (const lane of tree.lanes) {
        if (lane.kind !== 'chain') continue;

        const centreY = spineCentreY.get(lane.anchorId) ?? 0;
        let cursorX = sizeOf(lane.anchorId).width / 2 + CDT_TREE_H_GAP;

        for (const id of lane.blockIds) {
            const size = sizeOf(id);
            positions.set(id, { x: cursorX, y: centreY - size.height / 2 });
            cursorX += size.width + CDT_TREE_H_GAP;
        }
    }

    // 3. Asides clear the widest point of the spine and run away from it, level
    //    with their anchor.
    for (const lane of tree.lanes) {
        if (lane.kind !== 'aside') continue;

        const centreY = spineCentreY.get(lane.anchorId) ?? 0;
        const leftwards = lane.side === 'left';
        let edgeX = leftwards ? -spineHalfWidth - CDT_TREE_ASIDE_GAP : spineHalfWidth + CDT_TREE_ASIDE_GAP;

        for (const id of lane.blockIds) {
            const size = sizeOf(id);
            const x = leftwards ? edgeX - size.width : edgeX;
            positions.set(id, { x, y: centreY - size.height / 2 });
            edgeX = leftwards ? x - CDT_TREE_H_GAP : x + size.width + CDT_TREE_H_GAP;
        }
    }

    // 4. One connector per edge endpoint, so no two edges can ever share one, and
    //    fanned along its side so several arriving at one block do not stack on a
    //    single pixel. Incoming and outgoing share one fan per side, since they
    //    share the pixels. `(i + 1) / (k + 1)` leaves a lone connector at the
    //    centre, which is where every side used to put all of them.
    const outPorts = new Map<string, CdtTreeConnector[]>();
    const inPorts = new Map<string, CdtTreeConnector[]>();

    const bySide = new Map<string, Endpoint[]>();
    for (const edge of tree.edges) {
        collect(bySide, { blockId: edge.from, side: edge.fromSide, id: outputConnectorId(edge.id), out: true });
        collect(bySide, { blockId: edge.to, side: edge.toSide, id: inputConnectorId(edge.id), out: false });
    }

    for (const group of bySide.values()) {
        group.forEach((endpoint, index) => {
            push(endpoint.out ? outPorts : inPorts, endpoint.blockId, {
                id: endpoint.id,
                side: endpoint.side,
                offset: (index + 1) / (group.length + 1),
            });
        });
    }

    // 5. Normalise to the origin so tests can compare coordinates directly and
    //    `fitToScreen` has a clean bounding box to work with.
    const placed: CdtTreePositionedBlock[] = tree.blocks.map((block) => {
        return {
            ...block,
            shape: SHAPE_BY_KIND[block.kind],
            size: blockSize(block),
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
