import { ConditionGroup } from '../../../core/models/decision-table.model';

/**
 * The Route Code / Continue rule of a Classification Decision Table row.
 *
 * A matched row leaves in one of two ways: it names a route, or it continues to
 * the next rule. A route is terminal, so Continue has nothing to do while a route
 * code is set; a row with neither is incomplete and is flagged in the grid.
 *
 * Everything here reads the row and never writes it. Saved rows that break the
 * rule are shown as they are: a row with neither is flagged red, and a row with
 * both shows its Continue tick dimmed. They are corrected only when the user
 * edits the route code.
 */

/** A route code counts only when it has visible characters. */
export function hasRouteCode(row: ConditionGroup | null | undefined): boolean {
    return !!row?.route_code?.trim();
}

/** `continue` is the legacy spelling of `continue_flag`; same precedence as `payload.ts`. */
export function continuesAfterMatch(row: ConditionGroup | null | undefined): boolean {
    return !!(row?.continue_flag ?? row?.continue);
}

/** True when the row neither routes nor continues — the Route Code cell turns red. */
export function isMissingRouteOrContinue(row: ConditionGroup | null | undefined): boolean {
    return !!row && !hasRouteCode(row) && !continuesAfterMatch(row);
}

/**
 * True when the row has both a route code and Continue ticked. The route wins,
 * so the Continue tick has no effect and the grid dims it.
 */
export function isContinueIgnored(row: ConditionGroup | null | undefined): boolean {
    return hasRouteCode(row) && continuesAfterMatch(row);
}

/**
 * A route code as typed into the grid or read from an import, with leading and trailing whitespace
 * removed, so the grid, the canvas port and the saved row all hold the same code.
 * Anything that is not a string (for example, null) becomes empty.
 */
export function normalizeRouteCode(value: unknown): string {
    return typeof value === 'string' ? value.trim() : '';
}

/**
 * The `continue_flag` a row should hold after its route code changed from
 * `previousCode` to `nextCode`, or null when the edit should leave it alone.
 *
 * Naming a route unticks Continue. Clearing a route ticks it back. An edit that
 * keeps the code empty (for example, whitespace only) changes nothing, so a
 * Continue the user deliberately unticked stays unticked and the row stays red.
 */
export function continueFlagAfterRouteCodeEdit(
    previousCode: string | null | undefined,
    nextCode: string | null | undefined
): boolean | null {
    const hadCode = !!previousCode?.trim();
    const hasCode = !!nextCode?.trim();

    if (hasCode) return false;
    if (hadCode) return true;
    return null;
}
