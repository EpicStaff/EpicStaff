import {
    checkTestPayloadText,
    describeTestRunBlocker,
    FIX_TEST_PAYLOAD_JSON_MESSAGE,
    formatTestPayload,
    resolveSavedTestPayload,
    RUN_ALREADY_STARTING_MESSAGE,
} from './check-test-payload-text';

describe('checkTestPayloadText', () => {
    it('parses a payload and runs the validator on it, keeping its errors and hints apart', () => {
        const validator = vi.fn(() => ({ errors: ['rule broken'], hints: ['do this first'] }));

        expect(checkTestPayloadText('{"a": 1}', validator)).toEqual({
            payload: { a: 1 },
            parseError: null,
            ruleErrors: ['rule broken'],
            hints: ['do this first'],
        });
        expect(validator).toHaveBeenCalledWith({ a: 1 });
    });

    it('reports a parse error without running the validator', () => {
        const validator = vi.fn(() => ({ errors: ['rule broken'], hints: ['do this first'] }));

        const check = checkTestPayloadText('[]', validator);

        expect(check).toEqual({
            payload: null,
            parseError: 'Test payload must be a JSON object.',
            ruleErrors: [],
            hints: [],
        });
        expect(validator).not.toHaveBeenCalled();
    });

    it('has no rule errors or hints without a validator', () => {
        const check = checkTestPayloadText('{}');
        expect(check.ruleErrors).toEqual([]);
        expect(check.hints).toEqual([]);
    });
});

describe('resolveSavedTestPayload', () => {
    const saved = { saved: true };

    it('stores an edited payload that parses, even when it breaks node rules', () => {
        const check = checkTestPayloadText('{"edited": 1}', () => ({ errors: ['rule broken'], hints: [] }));
        expect(resolveSavedTestPayload(check, true, saved)).toEqual({ edited: 1 });
    });

    it('keeps the saved payload while the text does not parse', () => {
        expect(resolveSavedTestPayload(checkTestPayloadText('{"edited": '), true, saved)).toBe(saved);
    });

    it('keeps the saved payload until the user edits (a seeded sample is not stored)', () => {
        expect(resolveSavedTestPayload(checkTestPayloadText('{"seed": 1}'), false, saved)).toBe(saved);
        expect(resolveSavedTestPayload(checkTestPayloadText('{"seed": 1}'), false, undefined)).toEqual({});
    });
});

describe('describeTestRunBlocker', () => {
    it('blocks while a run is starting, before looking at the payload', () => {
        expect(describeTestRunBlocker(checkTestPayloadText('nope'), true)).toBe(RUN_ALREADY_STARTING_MESSAGE);
    });

    it('asks to fix text that does not parse', () => {
        expect(describeTestRunBlocker(checkTestPayloadText('nope'), false)).toBe(FIX_TEST_PAYLOAD_JSON_MESSAGE);
    });

    it('shows the first node rule error', () => {
        const check = checkTestPayloadText('{}', () => ({ errors: ['first', 'second'], hints: ['hint'] }));
        expect(describeTestRunBlocker(check, false)).toBe('first');
    });

    it('blocks on a node rule hint, showing it as the reason', () => {
        const check = checkTestPayloadText('{}', () => ({ errors: [], hints: ['select fields first'] }));
        expect(describeTestRunBlocker(check, false)).toBe('select fields first');
    });

    it('allows a valid payload', () => {
        expect(describeTestRunBlocker(checkTestPayloadText('{}'), false)).toBeNull();
    });
});

describe('formatTestPayload', () => {
    it('pretty-prints with two-space indentation', () => {
        expect(formatTestPayload({ a: { b: 1 } })).toBe('{\n  "a": {\n    "b": 1\n  }\n}');
    });
});
