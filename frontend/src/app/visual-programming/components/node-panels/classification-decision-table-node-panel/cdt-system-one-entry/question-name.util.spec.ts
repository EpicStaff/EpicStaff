import { isCompleteQuestion, isValidQuestionName } from './question-name.util';

describe('isValidQuestionName', () => {
    it.each([
        ['is_engineering', true],
        ['q1', true],
        ['match', true],
        ['_x', false],
        ['__class__', false],
        ['class', false],
        ['None', false],
        ['my-q', false],
        ['my q', false],
        ['1st', false],
        ['', false],
    ])('%j -> %s', (name, expected) => {
        expect(isValidQuestionName(name)).toBe(expected);
    });
});

describe('isCompleteQuestion', () => {
    const levels = (count: number): string[] => Array.from({ length: count }, (_, index) => `level ${index}`);

    it.each<[string, string, unknown, boolean]>([
        ['a noul question without criteria', 'q', { type: 'noul', instructions: 'Is it?' }, true],
        [
            'a noul question with both meanings',
            'q',
            { type: 'noul', instructions: 'x', criteria: { true: 'a', false: 'b' } },
            true,
        ],
        [
            'a noul question with an unknown criteria key',
            'q',
            { type: 'noul', instructions: 'x', criteria: { maybe: 'a' } },
            false,
        ],
        ['blank instructions', 'q', { type: 'noul', instructions: '   ' }, false],
        ['a bad name', 'class', { type: 'noul', instructions: 'x' }, false],
        [
            'a choice with one option',
            'q',
            { type: 'choice', instructions: 'x', criteria: { eng: 'Engineering' } },
            true,
        ],
        ['a choice with no options', 'q', { type: 'choice', instructions: 'x', criteria: {} }, false],
        [
            'a choice with the most options',
            'q',
            { type: 'choice', instructions: 'x', criteria: Object.fromEntries(levels(255).map((key) => [key, 'd'])) },
            true,
        ],
        [
            'a choice over the most options',
            'q',
            { type: 'choice', instructions: 'x', criteria: Object.fromEntries(levels(256).map((key) => [key, 'd'])) },
            false,
        ],
        ['a score with ten levels', 'q', { type: 'score', instructions: 'x', criteria: levels(10) }, true],
        ['a score with eleven levels', 'q', { type: 'score', instructions: 'x', criteria: levels(11) }, false],
        ['a score with no levels', 'q', { type: 'score', instructions: 'x', criteria: [] }, false],
        ['an unknown type', 'q', { type: 'rank', instructions: 'x' }, false],
        ['an extra key', 'q', { type: 'noul', instructions: 'x', note: 'y' }, false],
        ['not an object', 'q', 'noul', false],
    ])('%s', (_label, name, question, expected) => {
        expect(isCompleteQuestion(name, question)).toBe(expected);
    });
});
