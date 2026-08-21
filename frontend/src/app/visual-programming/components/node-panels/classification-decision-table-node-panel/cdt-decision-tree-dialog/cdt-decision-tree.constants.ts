import { CdtTreeBlockKind, CdtTreeShape, CdtTreeSize } from './cdt-decision-tree.model';

/** Which of the five legend shapes each block kind is drawn as. */
export const SHAPE_BY_KIND: Readonly<Record<CdtTreeBlockKind, CdtTreeShape>> = {
    'table-entered': 'terminator',
    'table-left': 'terminator',
    'pre-computation': 'predefined-process',
    'post-computation': 'predefined-process',
    'read-variables': 'data',
    'row-prompt': 'data',
    'row-decision': 'decision',
    'row-manipulation': 'process',
    // Rendered as a process rectangle with a `--marker` modifier so the legend
    // stays at exactly the five shapes of the mockup.
    'row-captured': 'process',
    'row-continue': 'predefined-process',
    'default-continue': 'predefined-process',
    'error-continue': 'predefined-process',
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
    'table-left': false,
    'pre-computation': true,
    'post-computation': true,
    'read-variables': false,
    'row-prompt': true,
    'row-decision': true,
    'row-manipulation': true,
    'row-captured': false,
    'row-continue': false,
    'default-continue': false,
    'error-continue': false,
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
};

export interface CdtTreeIcon {
    /** Sprite id without the `icon-` prefix, as `app-svg-icon` expects it. */
    readonly name: string;
    readonly width: string;
    readonly height: string;
}

export const ICON_BY_SHAPE: Readonly<Record<CdtTreeShape, CdtTreeIcon>> = {
    terminator: { name: 'tree-terminator', width: '16px', height: '16px' },
    'predefined-process': { name: 'tree-computation', width: '18px', height: '16px' },
    data: { name: 'tree-vars', width: '16px', height: '16px' },
    decision: { name: 'tree-condition', width: '16px', height: '15px' },
    process: { name: 'tree-processing', width: '16px', height: '16px' },
};

export const CDT_TREE_BLOCK_TITLE_BAND = 42;

/** One clamped subtitle line: 0.75rem at a 1.3 line-height, rounded up. */
export const CDT_TREE_SUBTITLE_LINE_HEIGHT = 16;

/** Vertical gap between consecutive blocks on the spine. */
export const CDT_TREE_V_GAP = 56;

/** Horizontal gap between blocks of a row's action chain. */
export const CDT_TREE_H_GAP = 72;

/** Extra gap between the spine and the error lane on its left. */
export const CDT_TREE_ERROR_LANE_GAP = 96;

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
