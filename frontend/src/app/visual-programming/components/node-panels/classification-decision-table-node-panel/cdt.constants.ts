/**
 * Constants for the Classification Decision Table (CDT) module.
 */

// ── Column-kind discriminators ────────────────────────────────────────────────

/** String identifiers used as colId / field / mode discriminators. */
export const CDT_COLUMN_KIND = {
    EXPRESSION: 'expression',
    MANIPULATION: 'manipulation',
} as const;

export type CdtColumnKind = (typeof CDT_COLUMN_KIND)[keyof typeof CDT_COLUMN_KIND];

// ── Column-id prefixes ────────────────────────────────────────────────────────

export const CDT_FIELD_PREFIX = 'field_' as const;
export const CDT_MANIP_PREFIX = 'manip_' as const;

// ── Row heights ───────────────────────────────────────────────────────────────

/**
 * Row height (px) configured in ag-Grid's `gridOptions.rowHeight`.
 * NOTE: intentionally different from CDT_OVERLAY_ROW_HEIGHT — do NOT unify.
 */
export const CDT_GRID_ROW_HEIGHT = 50;

/**
 * Row height (px) used by the collapsed-group overlay position calculation.
 * NOTE: intentionally different from CDT_GRID_ROW_HEIGHT — do NOT unify.
 */
export const CDT_OVERLAY_ROW_HEIGHT = 40;

// ── Expression-builder popup ──────────────────────────────────────────────────

/** Fixed pixel width of the expression-builder popup editor. */
export const CDT_EXPRESSION_EDITOR_POPUP_WIDTH = 660;

// ── LLM label fallback ────────────────────────────────────────────────────────

/** Fallback display label used when no LLM config is selected. */
export const CDT_DEFAULT_LLM_LABEL = 'Default LLM';

// ── Header auto-collapse ──────────────────────────────────────────────────────

/** Grid scrollTop (px) past which the panel's node-header block collapses. */
export const CDT_HEADER_COLLAPSE_AT = 24;

/** Grid scrollTop (px) below which it expands again. Lower than the collapse
 *  threshold on purpose: the gap is hysteresis, so a scroll parked near the
 *  boundary cannot flip the header back and forth. */
export const CDT_HEADER_EXPAND_AT = 8;

/**
 * Minimum scrollable overflow (scrollHeight - clientHeight, px) required before the header is
 * allowed to collapse; it gates the collapse direction only, never re-expansion. Collapsing hands
 * ~96px of header height back to the scroller, raising clientHeight and lowering maxScroll by the
 * same amount — so unless the overflow clears CDT_HEADER_EXPAND_AT + 96 = 104, collapsing would
 * clamp scrollTop under the expand threshold and flip the header straight back. 104 is the floor;
 * 120 carries margin for a taller header.
 */
export const CDT_HEADER_COLLAPSE_MIN_SCROLLABLE = 120;
