import { slugifyPortName } from '../../../core/helpers/helpers';
import { ConditionGroup } from '../../../core/models/decision-table.model';

/**
 * The Route Code / Continue rule of a Classification Decision Table row.
 *
 * A matched row leaves in one of two ways: it names a route, or it continues to
 * the next rule; a row with neither is incomplete and is flagged in the grid.
 *
 * When a row has both, which one wins depends on the canvas. The engine stops on
 * the row's `next_node`, so a route code wired to a node wins and Continue does
 * nothing. A route code wired to nothing never reaches the engine as a target, so
 * Continue applies and the route code is the part that does nothing.
 *
 * The editor keeps the second case from arising: the canvas refuses to wire a
 * route code whose row has Continue on, and ticking Continue on a wired route
 * code asks before removing the connection.
 *
 * Everything here reads the row and never writes it. Saved rows that break the
 * rule are shown as they are: a row with neither is flagged red, a wired route
 * code with Continue ticked is flagged red too, and an unwired route code with
 * Continue ticked is shown dimmed. The user corrects them; nothing here does.
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
 * True when the row has a route code and Continue ticked, and the route code's
 * output port leads to no node (`routeHasTarget` false). Continue applies, so the
 * route code has no effect and the grid dims it.
 *
 * A wired route code with Continue ticked is the opposite case; see
 * `isRouteContinueConflict`.
 */
export function isRouteCodeIgnored(row: ConditionGroup | null | undefined, routeHasTarget: boolean): boolean {
    return hasRouteCode(row) && continuesAfterMatch(row) && !routeHasTarget;
}

/**
 * True when the row has a route code wired to a node (`routeHasTarget` true) and
 * Continue ticked. The route wins and Continue silently does nothing, so the grid
 * flags the row as an error for the user to fix: remove the connection or untick
 * Continue. The editor no longer lets the user create this state (the canvas
 * refuses the connection, the grid asks before removing it), so it comes only
 * from saved data and is never corrected automatically.
 */
export function isRouteContinueConflict(row: ConditionGroup | null | undefined, routeHasTarget: boolean): boolean {
    return hasRouteCode(row) && continuesAfterMatch(row) && routeHasTarget;
}

/** Mirrors the port id built by `generatePortsForClassificationDecisionTableNode` (`slugifyPortName`). */
export function slugifyRouteCode(routeCode: string): string {
    return slugifyPortName(routeCode);
}

/**
 * The id of the output port the row's route code owns on table `nodeId`, or null
 * when the row has no route code.
 *
 * Built from the untrimmed `route_code`, exactly as
 * `generatePortsForClassificationDecisionTableNode`, the load mapper and
 * `FlowService` build it. Saved data can hold `"A "` next to `"A"`: those are two
 * ports, and trimming here would point at the wrong one.
 */
export function routePortIdForRow(nodeId: string, row: ConditionGroup | null | undefined): string | null {
    if (!hasRouteCode(row)) return null;
    return `${nodeId}_decision-route-${slugifyRouteCode(row?.route_code ?? '')}`;
}

/**
 * True when `portId` is a route-code output port of table `nodeId` and a row that
 * owns it has Continue ticked. Such a port must not be wired: Continue wins, and a
 * connection would silently make the route win instead. Rows sharing a port share
 * its target, so one ticked row is enough.
 */
export function isRoutePortBlockedByContinue(rows: readonly ConditionGroup[], nodeId: string, portId: string): boolean {
    return rows.some((row) => continuesAfterMatch(row) && routePortIdForRow(nodeId, row) === portId);
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
