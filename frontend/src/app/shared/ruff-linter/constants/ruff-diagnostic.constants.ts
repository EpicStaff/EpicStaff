/**
 * Ruff rule codes that mean the code is not parseable Python.
 *
 * These are the only diagnostics that must block saving: everything else Ruff
 * reports (E501 line-too-long, F401 unused-import, I001 unsorted-imports, ...)
 * is a style or hygiene violation that still runs fine, so it is surfaced in the
 * editor as a non-blocking marker instead - see the prefix lists below.
 *
 * Ruff 0.15 reports parse failures as `invalid-syntax`; older releases used the
 * pycodestyle-style `E999`. Both are kept so a version bump cannot silently drop
 * the gate.
 */
export const RUFF_SYNTAX_ERROR_CODES: ReadonlySet<string> = new Set(['invalid-syntax', 'E999']);

/**
 * Rule families whose findings usually mean the code is wrong even though it parses
 * (F821 undefined-name, F811 redefinition, F841 unused local, ...). Shown as warnings
 * so they stand out from the purely cosmetic rules below.
 */
export const RUFF_LIKELY_BUG_PREFIXES: readonly string[] = ['F'];

/**
 * pycodestyle rule families: real findings, but cosmetic (E501 line-too-long,
 * W291 trailing-whitespace). Shown as info so a wall of long lines - the usual state
 * of a built-in tool - does not read like something is broken.
 */
export const RUFF_STYLE_PREFIXES: readonly string[] = ['E', 'W'];
