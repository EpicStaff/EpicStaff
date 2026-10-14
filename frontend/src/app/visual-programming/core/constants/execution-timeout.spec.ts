import { NodeType } from '@shared/models';

import {
    defaultExecutionTimeoutMinutes,
    isExecutionTimeoutNodeType,
    isValidExecutionTimeout,
} from './execution-timeout';

describe('execution timeout defaults', () => {
    it('gives nodes running user code 3 minutes', () => {
        expect(defaultExecutionTimeoutMinutes(NodeType.PYTHON, 60)).toBe(3);
        expect(defaultExecutionTimeoutMinutes(NodeType.WEBHOOK_TRIGGER, 60)).toBe(3);
        expect(defaultExecutionTimeoutMinutes(NodeType.CLASSIFICATION_TABLE, 60)).toBe(3);
    });

    it('gives nodes running built-in code over user files the whole ceiling', () => {
        expect(defaultExecutionTimeoutMinutes(NodeType.FILE_EXTRACTOR, 60)).toBe(60);
        expect(defaultExecutionTimeoutMinutes(NodeType.AUDIO_TO_TEXT, 60)).toBe(60);
    });

    it('never gives user code more than a ceiling below 3 minutes', () => {
        expect(defaultExecutionTimeoutMinutes(NodeType.PYTHON, 2)).toBe(2);
        expect(defaultExecutionTimeoutMinutes(NodeType.WEBHOOK_TRIGGER, 1)).toBe(1);
        expect(defaultExecutionTimeoutMinutes(NodeType.CLASSIFICATION_TABLE, 2)).toBe(2);
    });

    it('knows exactly the five node types that run code in the sandbox', () => {
        const withTimeout = Object.values(NodeType).filter((type) => isExecutionTimeoutNodeType(type));

        expect(withTimeout.sort()).toEqual(
            [
                NodeType.PYTHON,
                NodeType.WEBHOOK_TRIGGER,
                NodeType.CLASSIFICATION_TABLE,
                NodeType.FILE_EXTRACTOR,
                NodeType.AUDIO_TO_TEXT,
            ].sort()
        );
    });
});

describe('isValidExecutionTimeout', () => {
    it.each([1, 3, 60, 100_000])('accepts %s whole minutes, with no upper bound', (minutes) => {
        expect(isValidExecutionTimeout(minutes)).toBe(true);
    });

    it.each([0, -1, 0.5, 2.5, null, undefined, '3', Number.NaN, Number.POSITIVE_INFINITY])('rejects %s', (minutes) => {
        expect(isValidExecutionTimeout(minutes)).toBe(false);
    });
});
