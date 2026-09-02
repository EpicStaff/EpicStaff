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
 * `CDT_TREE_SUBTITLE_CODE_LINES` lines instead, with the full text in the detail window,
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

/**
 * The design's measurements, per kind rather than per shape.
 *
 * Two kinds can share a silhouette and still be drawn at different sizes — the
 * parallelogram is both `Read variables` and a rule's prompt, and the design gives
 * them 187x42 and 286x60. Where a kind appears here its box is taken verbatim,
 * including the height: these are the drawn boxes, not minimums to grow from.
 * Anything absent falls back to `MIN_SIZE_BY_SHAPE` and the derived height.
 *
 * Fractions in the mockup (233.64, 187.29, 133.94) are rounded to whole pixels —
 * a half-pixel box puts the outline's 1px stroke across two device rows and
 * renders it soft.
 */
export const MIN_SIZE_BY_KIND: Readonly<Partial<Record<CdtTreeBlockKind, CdtTreeSize>>> = {
    'table-entered': { width: 196, height: 42 },
    'exit-terminator': { width: 196, height: 42 },
    // The mockup's 114x18 for these is a text layer, not a box — 18px is one title
    // line with nothing left for the padding around it. They take the decision's
    // width and the base row height instead, which also lines them up with the
    // rule column they sit above.
    'pre-computation': { width: 234, height: 42 },
    'post-computation': { width: 234, height: 42 },
    'read-variables': { width: 187, height: 42 },
    'row-decision': { width: 234, height: 134 },
    'row-prompt': { width: 286, height: 60 },
    'row-manipulation': { width: 164, height: 60 },
};

/**
 * How far the rules region's outline stands off the blocks it encloses.
 *
 * It has to clear `CDT_TREE_EDGE_OFFSET` by a visible margin, not merely exceed
 * it: the exit edges all drop through a corridor that far past the chains, so at
 * 28 the outline ran four pixels from a column of arrows and read as one of them.
 */
export const CDT_TREE_REGION_PADDING = 48;

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

/** Perpendicular shift of an edge label, so the chip clears its own line. */
export const CDT_TREE_EDGE_LABEL_OFFSET = -12;

/** Padding passed to `fitToScreen` so blocks never touch the viewport edge. */
export const CDT_TREE_FIT_PADDING = { x: 80, y: 60 } as const;

/**
 * Lines a block subtitle is allowed before the detail window takes over.
 *
 * The single source for two consumers: the layout reserves height for this many
 * lines where it derives a box, and the block's CSS clamps to it. Anything past
 * them is read in the detail window.
 *
 * One, because the design's measured boxes decide it: a 60px prompt spends 24 on
 * padding and 20 on its title line and the gap, which leaves 16 — exactly one
 * 12px line at a 1.3 line-height. A second line would overflow the silhouette by
 * about 15px, and the body centres its content, so it would spill from both ends.
 */
export const CDT_TREE_SUBTITLE_CODE_LINES = 1;

/**
 * Max characters of a subtitle before it is clipped with an ellipsis.
 *
 * Two clamped lines inside the narrowest text column a shape allows — the
 * diamond's, which is half the block's width — hold roughly this many at 12px.
 * The clamp is what stops the overflow; this only keeps the ellipsis honest, so
 * a subtitle ends in "…" rather than being cut mid-word by the line clamp.
 */
export const CDT_TREE_SUBTITLE_MAX_CHARS = 72;

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
    /**
     * Only when the route actually resolves: the engine breaks on `next_node`, so
     * a route that points nowhere still lets `continue` through.
     */
    routedContinueWarning: 'This rule routes, so Continue is ignored — an explicit route ends evaluation.',
    ruleFallback: (oneBased: number): string => `Rule ${oneBased}`,
    /**
     * Headings of the search dropdown. The number counts drawn rules, not grid
     * rows — a disabled rule is not evaluated and is not in the diagram, which
     * the toolbar's hidden-rules chip already says out loud.
     */
    entryGroup: 'Entry',
    exitGroup: 'Exit',
    rowGroup: (oneBased: number): string => `Row ${oneBased}`,
    promptLabel: (promptId: string): string => `Prompt "${promptId}"`,
    promptMissingWarning: 'Prompt not found in this table.',
    alwaysMatches: 'always matches',
    sharedRouteChip: (routeCode: string): string => `route ${routeCode}`,

    /**
     * Headings of the detail window's data section, one per openable kind.
     *
     * These name the *kind of content* rather than the block — the window already
     * carries the block's own name in its header, so repeating `Pre-computation`
     * underneath it said nothing. Both computation blocks therefore share one
     * heading.
     */
    detailPythonCode: 'Python Code',
    detailExpression: 'Expression',
    detailPrompt: 'Prompt',
    detailManipulation: 'Manipulation',

    /** The detail window's own chrome. */
    explanationHeading: 'Explanation',
    explainStep: 'Explain Step',
    generatedByLabel: 'Generated by:',

    /**
     * The Explanation section's states. The endpoint stores nothing, so a generated
     * explanation is kept on the node's metadata — see CdtExplanationStoreService.
     */
    explanationEmpty: 'No explanation yet.',
    explanationLoading: 'Generating an explanation…',

    /** Explaining the whole table from the toolbar. */
    explainAll: 'Explain All Steps',
    explainAllOutdatedOnly: 'Regenerate outdated steps only',
    explainAllBusy: (done: number, total: number): string => `Explaining ${done} / ${total}…`,
    explainAllStop: 'Stop',
    explainAllNothing: 'Every step already has an up-to-date explanation.',
    explainAllNothingOutdated: 'No step is outdated.',
    explainAllFailed: (count: number): string => `${count} step${count === 1 ? '' : 's'} could not be explained.`,

    /** The model picker behind the button's chevron. */
    explainMenuLabel: 'Choose the model that writes explanations',
    explainNoKey: 'no API key',
    explainNoConfigs: 'No LLMs are configured.',

    /** The stale-explanation marker, on the canvas and in the window. */
    outdatedTooltip: 'This step changed after its explanation was generated.',
    outdatedBadge: 'Outdated',

    /** Refusals, decided before any request is made. */
    explainUnsaved: 'Save the flow before explaining a step.',
    explainNoModel: 'Set a default LLM for this table, or on one of its prompts, before explaining a step.',

    /** Failures, mapped from the endpoint's own error codes. */
    explainModelGone: 'The LLM chosen for this table no longer exists. Pick another in the panel.',
    explainUpstreamFailed: 'The model did not return an explanation. Try again.',
    explainFailed: 'The explanation could not be generated.',
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
