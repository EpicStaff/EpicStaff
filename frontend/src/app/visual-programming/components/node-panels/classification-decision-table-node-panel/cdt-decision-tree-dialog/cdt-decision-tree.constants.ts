import { CdtTreeBlockKind, CdtTreeShape, CdtTreeSize } from './cdt-decision-tree.model';

/** Which of the five legend shapes each block kind is drawn as. */
export const SHAPE_BY_KIND: Readonly<Record<CdtTreeBlockKind, CdtTreeShape>> = {
    'table-entered': 'terminator',
    'exit-terminator': 'terminator',
    'pre-computation': 'predefined-process',
    'post-computation': 'predefined-process',
    'read-variables': 'data',
    'row-prompt': 'data',
    'row-decision': 'decision',
    'row-manipulation': 'process',
    'rules-region': 'region',
};

/**
 * Which kinds the design lets you open.
 *
 * A property of the kind, not of whether the block happens to carry content: the
 * mockup marks a block openable by elevating it, and `Read variables` is drawn
 * flat even though it holds the whole input map. Keeping the two apart is what
 * lets that map stay findable through the search while the block stays inert.
 */
export const CLICKABLE_BY_KIND: Readonly<Record<CdtTreeBlockKind, boolean>> = {
    'table-entered': false,
    'exit-terminator': false,
    'pre-computation': true,
    'post-computation': true,
    'read-variables': false,
    'row-prompt': true,
    'row-decision': true,
    'row-manipulation': true,
    'rules-region': false,
};

/**
 * Width, and the design's minimum height, per shape.
 *
 * The minimum is what a block carrying only a title occupies: 42px everywhere,
 * 134px for a decision diamond, whose text sits in the narrow middle band of the
 * shape. A block that also carries a subtitle grows past it — see `blockSize` in
 * the layout pass.
 *
 * Heights are derived, never measured: measuring would need a render-at-origin
 * pass plus a second change-detection cycle, would flash on open, and would make
 * the layout impure and untestable. Subtitles clamp to
 * `CDT_TREE_SUBTITLE_CODE_LINES` lines instead, with the full text in the popover,
 * and the height reserves exactly that many.
 */
export const MIN_SIZE_BY_SHAPE: Readonly<Record<CdtTreeShape, CdtTreeSize>> = {
    terminator: { width: 196, height: 42 },
    'predefined-process': { width: 268, height: 42 },
    data: { width: 268, height: 42 },
    decision: { width: 320, height: 134 },
    process: { width: 268, height: 42 },
    // The region is sized from what it encloses; the layout overrides this.
    region: { width: 0, height: 0 },
};

/** How far the rules region's outline stands off the blocks it encloses. */
export const CDT_TREE_REGION_PADDING = 28;

export interface CdtTreeIcon {
    /** Sprite id without the `icon-` prefix, as `app-svg-icon` expects it. */
    readonly name: string;
    readonly width: string;
    readonly height: string;
}

export const ICON_BY_SHAPE: Readonly<Partial<Record<CdtTreeShape, CdtTreeIcon>>> = {
    terminator: { name: 'tree-terminator', width: '16px', height: '16px' },
    'predefined-process': { name: 'tree-computation', width: '18px', height: '16px' },
    data: { name: 'tree-vars', width: '16px', height: '16px' },
    decision: { name: 'tree-condition', width: '16px', height: '15px' },
    process: { name: 'tree-processing', width: '16px', height: '16px' },
    // `region` has none: it is an outline, not a step.
};

export const CDT_TREE_BLOCK_TITLE_BAND = 42;

/** One clamped subtitle line: 0.75rem at a 1.3 line-height, rounded up. */
export const CDT_TREE_SUBTITLE_LINE_HEIGHT = 16;

/** Vertical gap between consecutive blocks on the spine. */
export const CDT_TREE_V_GAP = 56;

/** Horizontal gap between blocks of a row's action chain. */
export const CDT_TREE_H_GAP = 72;

/** Gap between the widest point of the spine and an aside lane beside it. */
export const CDT_TREE_ASIDE_GAP = 96;

/**
 * How far a connector stands off its block before the edge is allowed to turn.
 *
 * Passed to Foblex as `fOffset`, and read by the layout: a chain leaves from its
 * last block's right side, so this is also the width of the clear strip the exit
 * edges drop through, and where the route exit column is centred. Both have to
 * agree or the drop stops being a straight line.
 */
export const CDT_TREE_EDGE_OFFSET = 24;

/** Padding passed to `fitToScreen` so blocks never touch the viewport edge. */
export const CDT_TREE_FIT_PADDING = { x: 80, y: 60 } as const;

/**
 * Lines a block subtitle is allowed before the popover takes over.
 *
 * The single source for three consumers: the builder cuts a code preview to this
 * many lines, the layout reserves height for this many, and the block's CSS
 * clamps to it through `--cdt-tree-subtitle-lines`.
 */
export const CDT_TREE_SUBTITLE_CODE_LINES = 2;

/** Max characters of a subtitle before it is clipped with an ellipsis. */
export const CDT_TREE_SUBTITLE_MAX_CHARS = 120;

/**
 * Every phrase the builder chooses between, and every one it fills with data.
 *
 * Kept out of the builder so a rewording is a change here and nowhere else: the
 * builder emits a `CdtTreeTarget` state and renders it through this, and the specs
 * assert the state rather than the sentence. A block's own fixed name stays where
 * the block is built — it is that block's identity, not a rendering of anything.
 * The legend's labels already lived in this file for the same reason.
 */
export const CDT_TREE_COPY = {
    /**
     * The route lane names no specific node on purpose: several rules can route to
     * several different targets, and the design says only that the flow carries on.
     */
    relatedNode: 'Related node',
    /** The one edge a table with no enabled rule has: straight to its default. */
    noRowMatched: 'no row matched',
    endsFlow: 'Ends the flow',
    errorsEndFlow: 'Errors end the flow',
    /**
     * Only for a rule that has a target but no route code. A rule with neither is
     * an enrichment step that falls through on purpose — warning about those is
     * what made this badge noise before.
     */
    unsavedTargetWarning: 'This rule has a target but no route code, so the target is never saved.',
    ruleFallback: (oneBased: number): string => `Rule ${oneBased}`,
    promptLabel: (promptId: string): string => `Prompt "${promptId}"`,
    promptMissingWarning: 'Prompt not found in this table.',
    alwaysMatches: 'always matches',
    sharedRouteChip: (routeCode: string): string => `route ${routeCode}`,
} as const;

export interface CdtTreeLegendItem {
    readonly shape: CdtTreeShape;
    readonly label: string;
}

/** The sticky footer legend, in the mockup's order. */
export const CDT_TREE_LEGEND: readonly CdtTreeLegendItem[] = [
    { shape: 'terminator', label: 'Terminator — state in/out' },
    { shape: 'data', label: 'Data — variables bound' },
    { shape: 'process', label: 'Process — writes a variable' },
    { shape: 'decision', label: 'Decision — reads, never writes' },
    { shape: 'predefined-process', label: 'Predefined process — pre/post actions' },
];
