import { ConditionGroup } from '../../../core/models/decision-table.model';
import {
    continueFlagAfterRouteCodeEdit,
    continuesAfterMatch,
    hasRouteCode,
    isMissingRouteOrContinue,
    isRouteCodeIgnored,
    isRouteContinueConflict,
    isRoutePortBlockedByContinue,
    normalizeRouteCode,
    routePortIdForRow,
} from './cdt-route-continue.util';

function row(overrides: Partial<ConditionGroup>): ConditionGroup {
    return {
        group_name: 'Condition 1',
        group_type: 'complex',
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        ...overrides,
    };
}

describe('cdt-route-continue.util', () => {
    describe('hasRouteCode', () => {
        it('treats null, empty and whitespace-only codes as no code', () => {
            expect(hasRouteCode(row({ route_code: null }))).toBe(false);
            expect(hasRouteCode(row({ route_code: '' }))).toBe(false);
            expect(hasRouteCode(row({ route_code: '   \t' }))).toBe(false);
            expect(hasRouteCode(undefined)).toBe(false);
        });

        it('accepts a code with visible characters', () => {
            expect(hasRouteCode(row({ route_code: ' approve ' }))).toBe(true);
        });
    });

    describe('continuesAfterMatch', () => {
        it('prefers continue_flag over the legacy continue key, as payload.ts does', () => {
            expect(continuesAfterMatch(row({ continue_flag: false, continue: true }))).toBe(false);
            expect(continuesAfterMatch(row({ continue: true }))).toBe(true);
            expect(continuesAfterMatch(row({}))).toBe(false);
        });
    });

    describe('isMissingRouteOrContinue (red Route Code cell)', () => {
        it('flags a row with neither a route code nor Continue', () => {
            expect(isMissingRouteOrContinue(row({ route_code: '', continue_flag: false }))).toBe(true);
        });

        it('flags a whitespace-only route code with Continue unticked', () => {
            expect(isMissingRouteOrContinue(row({ route_code: '  ', continue_flag: false }))).toBe(true);
        });

        it('clears once a route code is entered', () => {
            expect(isMissingRouteOrContinue(row({ route_code: 'approve', continue_flag: false }))).toBe(false);
        });

        it('clears once Continue is ticked again', () => {
            expect(isMissingRouteOrContinue(row({ route_code: '', continue_flag: true }))).toBe(false);
        });

        it('does not flag a saved row that carries both a route and Continue', () => {
            expect(isMissingRouteOrContinue(row({ route_code: 'approve', continue_flag: true }))).toBe(false);
        });

        it('does not flag a missing row', () => {
            expect(isMissingRouteOrContinue(undefined)).toBe(false);
        });
    });

    describe('isRouteCodeIgnored (dimmed route code)', () => {
        it('is true for a route code wired to nothing with Continue ticked', () => {
            expect(isRouteCodeIgnored(row({ route_code: 'approve', continue_flag: true }), false)).toBe(true);
        });

        it('reads the legacy continue key', () => {
            expect(isRouteCodeIgnored(row({ route_code: 'approve', continue: true }), false)).toBe(true);
        });

        it('is false when the route code is wired to a node', () => {
            expect(isRouteCodeIgnored(row({ route_code: 'approve', continue_flag: true }), true)).toBe(false);
        });

        it('is false when Continue is unticked', () => {
            expect(isRouteCodeIgnored(row({ route_code: 'approve', continue_flag: false }), false)).toBe(false);
        });

        it('is false without a route code, including whitespace only', () => {
            expect(isRouteCodeIgnored(row({ route_code: '', continue_flag: true }), false)).toBe(false);
            expect(isRouteCodeIgnored(row({ route_code: '   ', continue_flag: true }), false)).toBe(false);
        });

        it('is false for a missing row', () => {
            expect(isRouteCodeIgnored(undefined, false)).toBe(false);
        });
    });

    describe('isRouteContinueConflict (red Route Code cell on saved data)', () => {
        it('is true for a route code wired to a node with Continue ticked', () => {
            expect(isRouteContinueConflict(row({ route_code: 'approve', continue_flag: true }), true)).toBe(true);
        });

        it('reads the legacy continue key', () => {
            expect(isRouteContinueConflict(row({ route_code: 'approve', continue: true }), true)).toBe(true);
        });

        it('clears once the connection is removed', () => {
            expect(isRouteContinueConflict(row({ route_code: 'approve', continue_flag: true }), false)).toBe(false);
        });

        it('clears once Continue is unticked', () => {
            expect(isRouteContinueConflict(row({ route_code: 'approve', continue_flag: false }), true)).toBe(false);
        });

        it('is false without a route code or row', () => {
            expect(isRouteContinueConflict(row({ route_code: '  ', continue_flag: true }), true)).toBe(false);
            expect(isRouteContinueConflict(undefined, true)).toBe(false);
        });
    });

    describe('routePortIdForRow', () => {
        it('builds the port id the canvas gives a route code', () => {
            expect(routePortIdForRow('node1', row({ route_code: 'Needs Review' }))).toBe(
                'node1_decision-route-needs-review'
            );
        });

        it('keeps surrounding whitespace, as the canvas port does, so "A " and "A" are different ports', () => {
            expect(routePortIdForRow('node1', row({ route_code: 'A ' }))).toBe('node1_decision-route-a-');
            expect(routePortIdForRow('node1', row({ route_code: 'A' }))).toBe('node1_decision-route-a');
        });

        it('is null without a route code', () => {
            expect(routePortIdForRow('node1', row({ route_code: '   ' }))).toBeNull();
            expect(routePortIdForRow('node1', row({ route_code: null }))).toBeNull();
            expect(routePortIdForRow('node1', undefined)).toBeNull();
        });
    });

    describe('isRoutePortBlockedByContinue (canvas refuses the connection)', () => {
        const portId = 'node1_decision-route-approve';

        it('blocks the port of a route code whose row has Continue ticked', () => {
            const rows = [row({ route_code: 'approve', continue_flag: true })];
            expect(isRoutePortBlockedByContinue(rows, 'node1', portId)).toBe(true);
        });

        it('blocks a shared port when any row owning it has Continue ticked', () => {
            const rows = [
                row({ route_code: 'approve', continue_flag: false }),
                row({ route_code: 'approve', continue: true }),
            ];
            expect(isRoutePortBlockedByContinue(rows, 'node1', portId)).toBe(true);
        });

        it('leaves the port free when Continue is unticked', () => {
            const rows = [row({ route_code: 'approve', continue_flag: false })];
            expect(isRoutePortBlockedByContinue(rows, 'node1', portId)).toBe(false);
        });

        it('ignores other ports, other nodes and rows without a route code', () => {
            const rows = [
                row({ route_code: 'reject', continue_flag: true }),
                row({ route_code: '', continue_flag: true }),
            ];
            expect(isRoutePortBlockedByContinue(rows, 'node1', portId)).toBe(false);
            expect(
                isRoutePortBlockedByContinue([row({ route_code: 'approve', continue_flag: true })], 'node2', portId)
            ).toBe(false);
            expect(isRoutePortBlockedByContinue(rows, 'node1', 'node1_decision-default')).toBe(false);
        });

        it('matches a saved route code with trailing whitespace to its own port only', () => {
            const rows = [row({ route_code: 'approve ', continue_flag: true })];
            expect(isRoutePortBlockedByContinue(rows, 'node1', 'node1_decision-route-approve-')).toBe(true);
            expect(isRoutePortBlockedByContinue(rows, 'node1', portId)).toBe(false);
        });
    });

    describe('normalizeRouteCode (route_code valueParser)', () => {
        it('strips leading and trailing whitespace', () => {
            expect(normalizeRouteCode('  approve 	')).toBe('approve');
        });

        it('keeps inner whitespace', () => {
            expect(normalizeRouteCode(' needs review ')).toBe('needs review');
        });

        it('turns whitespace-only into empty', () => {
            expect(normalizeRouteCode('   ')).toBe('');
        });

        it('turns non-strings into empty', () => {
            expect(normalizeRouteCode(null)).toBe('');
            expect(normalizeRouteCode(undefined)).toBe('');
            expect(normalizeRouteCode(42)).toBe('');
        });
    });

    describe('continueFlagAfterRouteCodeEdit', () => {
        it('unticks Continue when a route code is entered', () => {
            expect(continueFlagAfterRouteCodeEdit('', 'approve')).toBe(false);
            expect(continueFlagAfterRouteCodeEdit(null, 'approve')).toBe(false);
        });

        it('keeps Continue unticked when one route code is replaced by another', () => {
            expect(continueFlagAfterRouteCodeEdit('approve', 'reject')).toBe(false);
        });

        it('ticks Continue when the route code is cleared', () => {
            expect(continueFlagAfterRouteCodeEdit('approve', '')).toBe(true);
            expect(continueFlagAfterRouteCodeEdit('approve', null)).toBe(true);
        });

        it('treats clearing to whitespace as clearing', () => {
            expect(continueFlagAfterRouteCodeEdit('approve', '   ')).toBe(true);
        });

        it('leaves Continue alone when the code stays empty', () => {
            expect(continueFlagAfterRouteCodeEdit('', '  ')).toBeNull();
            expect(continueFlagAfterRouteCodeEdit(undefined, '')).toBeNull();
        });
    });
});
