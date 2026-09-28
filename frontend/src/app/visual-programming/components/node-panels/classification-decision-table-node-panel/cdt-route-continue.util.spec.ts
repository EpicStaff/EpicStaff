import { ConditionGroup } from '../../../core/models/decision-table.model';
import {
    continueFlagAfterRouteCodeEdit,
    continuesAfterMatch,
    hasRouteCode,
    isContinueIgnored,
    isMissingRouteOrContinue,
    normalizeRouteCode,
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

    describe('isContinueIgnored (dimmed Continue checkbox)', () => {
        it('is true when the row has a route code and Continue ticked', () => {
            expect(isContinueIgnored(row({ route_code: 'approve', continue_flag: true }))).toBe(true);
        });

        it('reads the legacy continue key', () => {
            expect(isContinueIgnored(row({ route_code: 'approve', continue: true }))).toBe(true);
        });

        it('is false when Continue is unticked', () => {
            expect(isContinueIgnored(row({ route_code: 'approve', continue_flag: false }))).toBe(false);
        });

        it('is false without a route code, including whitespace only', () => {
            expect(isContinueIgnored(row({ route_code: '', continue_flag: true }))).toBe(false);
            expect(isContinueIgnored(row({ route_code: '   ', continue_flag: true }))).toBe(false);
        });

        it('is false for a missing row', () => {
            expect(isContinueIgnored(undefined)).toBe(false);
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
