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
 * Fixed sizes per shape — the layout pass never measures the DOM.
 *
 * Measuring would need a render-at-origin pass plus a second change-detection
 * cycle, would flash on open, and would make the layout impure and untestable.
 * Subtitles clamp to two lines instead, with the full text in the popover.
 */
export const SIZE_BY_SHAPE: Readonly<Record<CdtTreeShape, CdtTreeSize>> = {
    terminator: { width: 240, height: 56 },
    'predefined-process': { width: 268, height: 76 },
    data: { width: 268, height: 76 },
    decision: { width: 320, height: 148 },
    process: { width: 268, height: 76 },
};

/** Vertical gap between consecutive blocks on the spine. */
export const CDT_TREE_V_GAP = 56;

/** Horizontal gap between blocks of a row's action chain. */
export const CDT_TREE_H_GAP = 72;

/** Extra gap between the spine and the error lane on its left. */
export const CDT_TREE_ERROR_LANE_GAP = 96;

/** Padding passed to `fitToScreen` so blocks never touch the viewport edge. */
export const CDT_TREE_FIT_PADDING = { x: 80, y: 60 } as const;

/** Max lines of code shown as a block subtitle before the popover takes over. */
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
