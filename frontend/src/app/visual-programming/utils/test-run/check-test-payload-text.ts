import { parseTestPayload, TriggerTestPayload } from './validate-test-payload';

/**
 * What node-specific rules say about a parsed test payload. Both kinds block a test run; they differ
 * only in how they are shown: an error is a problem in the payload, a hint is something to do first
 * that is not wrong with the payload (e.g. "select fields before running a test").
 */
export interface TestPayloadRuleMessages {
    errors: string[];
    hints: string[];
}

/** Node-specific rules for a parsed test payload. */
export type TestPayloadValidator = (payload: TriggerTestPayload) => TestPayloadRuleMessages;

export interface TestPayloadTextCheck {
    /** The parsed payload; null when the text is not a payload the backend accepts. */
    payload: TriggerTestPayload | null;
    /** Why the text could not be parsed into a payload. */
    parseError: string | null;
    /** The `validator` errors for a parsed payload. */
    ruleErrors: string[];
    /** The `validator` hints for a parsed payload: they block a run but are not payload errors. */
    hints: string[];
}

/** Everything a test payload editor needs to know about its text: what to save, run or report. */
export function checkTestPayloadText(
    text: string,
    validator: TestPayloadValidator | null = null
): TestPayloadTextCheck {
    const result = parseTestPayload(text);
    if (result.error !== undefined) {
        return { payload: null, parseError: result.error, ruleErrors: [], hints: [] };
    }
    const messages = validator?.(result.value);
    return {
        payload: result.value,
        parseError: null,
        ruleErrors: messages?.errors ?? [],
        hints: messages?.hints ?? [],
    };
}

/** The payload to store on the node: the edited payload when it parses, else the saved one. */
export function resolveSavedTestPayload(
    check: TestPayloadTextCheck,
    isEdited: boolean,
    savedPayload: TriggerTestPayload | undefined
): TriggerTestPayload {
    if (isEdited && check.payload !== null) {
        return check.payload;
    }
    return savedPayload ?? {};
}

export const RUN_ALREADY_STARTING_MESSAGE = 'A run is starting...';
export const FIX_TEST_PAYLOAD_JSON_MESSAGE = 'Fix the test payload JSON to run';

/** Why "Run with test payload" is disabled, or null when it can run. */
export function describeTestRunBlocker(check: TestPayloadTextCheck, isRunStarting: boolean): string | null {
    if (isRunStarting) {
        return RUN_ALREADY_STARTING_MESSAGE;
    }
    if (check.parseError !== null) {
        return FIX_TEST_PAYLOAD_JSON_MESSAGE;
    }
    return check.ruleErrors[0] ?? check.hints[0] ?? null;
}

export function formatTestPayload(payload: TriggerTestPayload): string {
    return JSON.stringify(payload, null, 2);
}
