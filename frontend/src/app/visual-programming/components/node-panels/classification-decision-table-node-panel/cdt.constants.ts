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

// ── Route Code / Continue copy ────────────────────────────────────────────────

/** Route Code cell tooltip; see `cdt-route-continue.util.ts` for the rule. */
export const CDT_ROUTE_CONTINUE_COPY = {
    continueIgnored: 'Use one: a route code or Continue. With a route code, Continue is ignored.',
} as const;
