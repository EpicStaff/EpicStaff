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
    CDT_TREE_EDGE_OFFSET,
    CDT_TREE_H_GAP,
    CDT_TREE_REGION_PADDING,
    CDT_TREE_SUBTITLE_CODE_LINES,
    CDT_TREE_SUBTITLE_LINE_HEIGHT,
    CDT_TREE_V_GAP,
    MIN_SIZE_BY_SHAPE,
    SHAPE_BY_KIND,
} from './cdt-decision-tree.constants';
import {
    CdtTree,
    CdtTreeBlock,
    CdtTreeChainLane,
    CdtTreeConnector,
    CdtTreeExitColumn,
    CdtTreeLayout,
    CdtTreePoint,
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

interface CdtTreeBounds {
    readonly minX: number;
    readonly minY: number;
    readonly maxX: number;
    readonly maxY: number;
}

function boundsOf(
    ids: readonly string[],
    positions: Map<string, CdtTreePoint>,
    sizeOf: (id: string) => CdtTreeSize
): CdtTreeBounds | null {
    const placed = ids.map((id) => ({ point: positions.get(id), size: sizeOf(id) })).filter((entry) => !!entry.point);
    if (placed.length === 0) return null;

    return {
        minX: Math.min(...placed.map((entry) => entry.point!.x)),
        minY: Math.min(...placed.map((entry) => entry.point!.y)),
        maxX: Math.max(...placed.map((entry) => entry.point!.x + entry.size.width)),
        maxY: Math.max(...placed.map((entry) => entry.point!.y + entry.size.height)),
    };
}

/**
 * Where an exit column's centre goes.
 *
 * Each anchor puts the column directly under whatever feeds it, so that edge is a
 * straight vertical drop. None of them ever moves a column left of the one before
 * it, which is what keeps a table with no rules — or with very short chains —
 * from stacking two columns on top of each other. `region` falls back to that
 * spacing when there are no rules and so no region to sit under.
 */
function columnCentre(
    anchor: CdtTreeExitColumn['anchor'],
    width: number,
    previousRight: number,
    corridorX: number,
    regionCentreX: number | null
): number {
    const afterPrevious = previousRight + CDT_TREE_H_GAP + width / 2;

    switch (anchor) {
        case 'spine':
            return 0;
        case 'region':
            return regionCentreX === null ? afterPrevious : Math.max(regionCentreX, afterPrevious);
        case 'chain-corridor':
            return Math.max(corridorX, afterPrevious);
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

    const sizeOverrides = new Map<string, CdtTreeSize>();
    const sizeOf = (id: string): CdtTreeSize => sizeOverrides.get(id) ?? blockSize(blockById(id));

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

    // 2. Each chain runs right from its anchor, vertically centred on it, and every
    //    chain ends at the same x. Right-aligning them lines the branches up into
    //    columns, and — the reason it matters — it leaves the strip past that
    //    shared edge free. A chain's exit edge leaves its last block sideways and
    //    drops through that strip, so it never crosses the branch below it.
    const chains = tree.lanes.filter(
        (lane): lane is CdtTreeChainLane => lane.kind === 'chain' && !!lane.blockIds.length
    );

    const chainSpan = (lane: CdtTreeChainLane): number =>
        lane.blockIds.reduce((total, id) => total + sizeOf(id).width, 0) + CDT_TREE_H_GAP * (lane.blockIds.length - 1);

    const chainsRight = Math.max(
        ...chains.map((lane) => sizeOf(lane.anchorId).width / 2 + CDT_TREE_H_GAP + chainSpan(lane)),
        0
    );

    for (const lane of chains) {
        const centreY = spineCentreY.get(lane.anchorId) ?? 0;
        let cursorX = chainsRight - chainSpan(lane);

        for (const id of lane.blockIds) {
            const size = sizeOf(id);
            positions.set(id, { x: cursorX, y: centreY - size.height / 2 });
            cursorX += size.width + CDT_TREE_H_GAP;
        }
    }

    /** The clear vertical strip every chain exit drops through. */
    const corridorX = chainsRight + CDT_TREE_EDGE_OFFSET;

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

    // 4. The region wraps what it covers, so it can only be sized once those are
    //    placed. It is the one block whose size the layout decides.
    let regionCentreX: number | null = null;

    for (const lane of tree.lanes) {
        if (lane.kind !== 'region') continue;

        const bounds = boundsOf(lane.coversIds, positions, sizeOf);
        if (!bounds) continue;

        sizeOverrides.set(lane.blockId, {
            width: bounds.maxX - bounds.minX + CDT_TREE_REGION_PADDING * 2,
            height: bounds.maxY - bounds.minY + CDT_TREE_REGION_PADDING * 2,
        });
        positions.set(lane.blockId, {
            x: bounds.minX - CDT_TREE_REGION_PADDING,
            y: bounds.minY - CDT_TREE_REGION_PADDING,
        });

        regionCentreX = (bounds.minX + bounds.maxX) / 2;
    }

    // 5. The exit row clears everything above it — including the region, which
    //    reaches lower than the last rule — and runs its columns left to right.
    const exitsLane = tree.lanes.find((lane) => lane.kind === 'exits');
    if (exitsLane) {
        const placedBottom = Math.max(...[...positions].map(([id, point]) => point.y + sizeOf(id).height), 0);

        let previousRight = 0;
        for (const column of exitsLane.columns) {
            const width = Math.max(...column.blockIds.map((id) => sizeOf(id).width), 0);
            const centreX = columnCentre(column.anchor, width, previousRight, corridorX, regionCentreX);

            let cursorY = placedBottom + CDT_TREE_V_GAP;
            for (const id of column.blockIds) {
                const size = sizeOf(id);
                positions.set(id, { x: centreX - size.width / 2, y: cursorY });
                cursorY += size.height + CDT_TREE_V_GAP;
            }

            previousRight = centreX + width / 2;
        }
    }

    // 6. One connector per edge endpoint, so no two edges can ever share one — see
    //    `outputConnectorId`. All of them sit at the centre of their side, which is
    //    what keeps the edges straight: no block ever has two edges leaving the
    //    same side, so the only thing centring costs is that edges converging on
    //    one block meet at a single point, which is how the mockup draws them.
    const outPorts = new Map<string, CdtTreeConnector[]>();
    const inPorts = new Map<string, CdtTreeConnector[]>();

    for (const edge of tree.edges) {
        push(outPorts, edge.from, { id: outputConnectorId(edge.id), side: edge.fromSide });
        push(inPorts, edge.to, { id: inputConnectorId(edge.id), side: edge.toSide });
    }

    // 5. Normalise to the origin so tests can compare coordinates directly and
    //    `fitToScreen` has a clean bounding box to work with.
    const placed: CdtTreePositionedBlock[] = tree.blocks.map((block) => {
        return {
            ...block,
            shape: SHAPE_BY_KIND[block.kind],
            size: sizeOf(block.id),
            position: positions.get(block.id) ?? { x: 0, y: 0 },
            outPorts: outPorts.get(block.id) ?? [],
            inPorts: inPorts.get(block.id) ?? [],
        };
    });

    const minX = Math.min(...placed.map((block) => block.position.x));
    const minY = Math.min(...placed.map((block) => block.position.y));
    const maxX = Math.max(...placed.map((block) => block.position.x + block.size.width));
    const maxY = Math.max(...placed.map((block) => block.position.y + block.size.height));

    // The layout has no say in reading order, but it is the pass that knows which
    // ids are real — so a group naming a block nobody drew is caught here.
    for (const group of tree.groups) {
        for (const id of group.blockIds) blockById(id);
    }

    return {
        title: tree.title,
        blocks: placed.map((block) => ({
            ...block,
            position: { x: block.position.x - minX, y: block.position.y - minY },
        })),
        edges: tree.edges,
        groups: tree.groups,
        bounds: { width: maxX - minX, height: maxY - minY },
        hiddenRowCount: tree.hiddenRowCount,
        rowCount: tree.rowCount,
    };
}
